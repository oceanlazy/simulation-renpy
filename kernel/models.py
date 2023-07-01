from __future__ import division
from builtins import object

import logging
import re

from collections import defaultdict, OrderedDict
from math import ceil
from kernel.orm import QuerySet
from kernel.settings import DEBUG_ROUTE_SEARCH, DEBUG_SET_POSITIONS, DEBUG_SIMULATION, PLAYER_ID
from kernel.simulation.plans.modifiers import PlanModifiersPosNeg, CharacterPlanModifiers
from kernel.utils import (
    get_value_replaced,
    get_value_replaced_second_char,
    get_filters_replaced,
    plan_pauses,
    qs_cache,
    qs_cache_relations,
    player_data,
    relations_cache,
    unicode
)

from kernel import renpy

logger_simulation = logging.getLogger('simulation')
logger_positions = logging.getLogger('positions')


class BaseModel(object):
    objects = None
    db_attrs_range = None
    db_objects = None
    db_objects_row = None
    mtm_data = None
    set_data = None
    __is_initialized = False
    __instances = {}

    def __init__(self, pk):
        if self.__is_initialized:
            return

        self.pk = pk
        self.db_objects_row = self.db_objects[pk]

        for key in self.db_objects_row:
            setattr(self, key, self.db_objects_row[key])

        self.__is_initialized = True

    def __new__(cls, pk):
        key = (cls.__name__, pk)
        if key in cls.__instances:
            return cls.__instances[key]
        instance = super(BaseModel, cls).__new__(cls)
        cls.__instances[key] = instance
        return instance

    def __str__(self):
        return str(self.pk)

    def __repr__(self):
        return str('{}({})'.format(self.__class__.__name__, self))

    def __lt__(self, other):
        return False

    def __le__(self, other):
        return False

    def __gt__(self, other):
        return False

    def __ge__(self, other):
        return False

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.id == other.id

    def __hash__(self):
        return self.id+len(self.__class__.__name__)+len(self.objects_fields)

    def __getattr__(self, item):
        if item in self.mto_data:
            data = self.mto_data[item]
            pk = getattr(self, data['from_id'])
            value = data['model'](pk) if pk else None
            setattr(self, item, value)
            return value
        elif item in self.set_data:
            data = self.set_data[item]
            value = data['model'].get_new_queryset(base_filters={data['target_id']: self.id})
            setattr(self, item, value)
            return value
        elif item in self.mtm_data:
            data = self.mtm_data[item]
            target_id_key = data['target_id']
            from_id_key = data['from_id']
            qs = QuerySet(
                model=data['model'],
                base_filters={
                    'id__in': [
                        row[target_id_key]
                        for row in data['through']['objects'].values()
                        if row[from_id_key] == self.id
                    ]
                }
            )
            setattr(self, item, qs)
            return qs
        return object.__getattribute__(self, item)

    def __getnewargs__(self):
        return self.pk,

    @classmethod
    def get_new_queryset(cls, base_filters=None):
        return QuerySet(cls, base_filters)

    @classmethod
    def clean_qs_cache(cls):
        cls_name = cls.__name__
        for qs_cache_key in qs_cache_relations[cls_name]:
            if qs_cache_key not in qs_cache:
                continue
            del qs_cache[qs_cache_key]
        del qs_cache_relations[cls_name]

    def clone(self, **kwargs):
        data = self.db_objects_row.copy()
        del data['id']
        data.update(kwargs)
        return self.create(**data)

    @classmethod
    def create(cls, **kwargs):
        data = {}
        instance_ids = {}

        if 'id' in kwargs:
            set_id = kwargs['id']
        else:
            set_id = max(cls.db_objects) + 1 if cls.db_objects else 1
            data['id'] = set_id

        for k in cls.objects_fields:
            if k == 'id':
                continue
            if k in kwargs:
                new_v = kwargs[k]
            elif k in cls.defaults:
                new_v = cls.defaults[k]
            else:
                data[k] = None
                continue

            if new_v and k.endswith('_id'):
                fk = k[:-3]
                if fk not in cls.mto_data:
                    raise ValueError('Model for field "{}" was not found. Hint: Rename "_id" to "_pk".'.format(k))
                instance_ids[fk] = cls.mto_data[fk]['model'](new_v)

            data[k] = new_v

        for k in set(cls.mto_data) & set(kwargs):
            if k in kwargs:
                v = kwargs[k]
                data['{}_id'.format(k)] = None if v is None else v.id
                instance_ids[k] = v

        cls.db_objects[set_id] = data
        instance = cls(set_id)
        for k in instance_ids:
            setattr(instance, k, instance_ids[k])
        cls.clean_qs_cache()

        return instance

    def update(self, **kwargs):
        if not kwargs:
            return

        for key in kwargs:
            value = kwargs[key]

            if key in self.db_attrs_range:
                mn = self.db_attrs_range[key]['min']
                mx = self.db_attrs_range[key]['max']
                if value < mn:
                    value = mn
                elif value > mx:
                    value = mx
            elif key in self.mto_data:
                mto_key = self.mto_data[key]['from_id']
                mto_value = value.id if value else None
                setattr(self, mto_key, mto_value)
                self.db_objects_row[mto_key] = mto_value
            elif key.endswith('_id'):
                mto_key = key[:-3]
                setattr(self, mto_key, self.mto_data.get(mto_key)['model'](value) if value else None)
            elif not hasattr(self, key):
                raise ValueError('field "{}" not found'.format(key))

            setattr(self, key, value)
            if key in self.objects_fields:
                self.db_objects_row[key] = value

        self.clean_qs_cache()

    def delete(self):
        if not self.id:
            return

        for rel_name in self.set_data:
            rel_target_id = self.set_data[rel_name]['target_id']
            for instance in getattr(self, rel_name).filter():
                instance.update(**{rel_target_id: None})

        del self.db_objects[self.pk]
        del self.__instances[(self.__class__.__name__, self.pk)]
        self.clean_qs_cache()
        self.id = self.pk = None # noqa


# Characters
class Plan(BaseModel):
    stages_next = {None: 'one', 'one': 'two', 'two': 'three', 'three': 'four', 'four': 'five', 'five': None}

    def __str__(self):
        return self.title

    def set_pause(
            self,
            char_id,
            current_seconds,
            is_interrupted=False,
            pause_seconds_default=None,
            pause_stage=None,
            is_first=True
    ):
        pause_seconds = pause_stage or self.time_pause
        if (
            pause_seconds and
            (is_interrupted or self.is_always_pause) and
            ((is_first and self.is_first_pause) or (not is_first and self.is_second_pause))
        ):
            if not pause_seconds or pause_seconds == -1:
                pass
            elif pause_seconds > 0:
                pause_seconds *= 60
            else:
                raise ValueError('Wrong pause: "{}"'.format(pause_seconds))
        elif pause_seconds_default:
            pause_seconds = pause_seconds_default
        elif is_interrupted:
            pause_seconds = 1
        else:
            return False
        plan_pauses[char_id][self.id] = -1 if pause_seconds == -1 else current_seconds + pause_seconds
        if DEBUG_SIMULATION:
            logger_simulation.info('set pause for {}({}) until {}'.format(
                self.title, Character(char_id).title, plan_pauses[char_id][self.id]
            ))

        return True

    @staticmethod
    def get_replaced_text(text, instance):
        return text.format(**{
            name: get_value_replaced(instance, name) for name in re.findall(r'{(.*?)}', text)
        })

    def get_event_description(self, instance):
        return self.get_replaced_text(self.event_desc, instance)

    def get_ask_player_description(self, instance):
        return self.get_replaced_text(self.ask_player_desc, instance)

    def get_beginning_text(self, instance):
        return self.get_replaced_text(self.beginning_text, instance)


class EventLog(BaseModel):
    def __str__(self):
        return '{}: {}{} - {}'.format(
            self.timestamp,
            self.first_character.title,
            '({})'.format(self.second_character.title) if self.second_character else '',
            self.plan.title
        )

    @classmethod
    def create_from_plan_data(cls, current_seconds, plan_data, **kwargs):
        plan = plan_data.plan
        super(EventLog, cls).create(
            timestamp=current_seconds,
            plan=plan,
            first_character=plan_data.first_character,
            second_character=plan_data.second_character,
            place=plan_data.first_character.place,
            is_important=plan.is_important_event,
            **kwargs
        )

    def get_description(self):
        return self.plan.get_event_description(self)


class PlanData(BaseModel):
    def __str__(self):
        items = ['{}({}): {}'.format(self.plan.title, self.plan_stage, self.first_character.title)]
        if self.second_character_id:
            items.append(' and {}'.format(self.second_character.title))
        return ''.join(items)

    def get_stage(self):
        return getattr(self.plan, self.plan_stage)

    def set_pause(self, char_id, current_seconds, is_interrupted=False, pause_seconds=None):
        stage = self.get_stage()
        pause_stage = stage.time_pause if stage else None
        return self.plan.set_pause(
            char_id, current_seconds, is_interrupted, pause_seconds, pause_stage, self.first_character_id == char_id
        )

    def next_or_finish(self, current_seconds):
        if not self.next_stage():
            self.finish_plan(current_seconds)

    def next_stage(self):
        next_stage = self.plan.stages_next[self.plan_stage]
        if not getattr(self.plan, next_stage):
            return False
        self.update(plan_stage=next_stage)
        return True

    def finish_plan(self, current_seconds, is_interrupted=False, pause_seconds=None):
        if DEBUG_SIMULATION:
            logger_simulation.info('finished plan {}'.format(self.plan.title))
        previous_to_delete = {}

        if self.first_character_id == PLAYER_ID or self.second_character_id == PLAYER_ID:
            if self.first_character_id == PLAYER_ID:
                player_data['suitable_places'] = []
            callback = getattr(renpy.store, 'finish_{}'.format(self.plan.title), None)
            if callback:
                callback(self)

        for char, previous in (
            (self.first_character, self.first_previous), (self.second_character, self.second_previous)
        ):
            if not char:
                continue
            if char.is_clone:
                char.delete()
                continue

            char.update(plan_data=None)
            self.set_pause(char.id, current_seconds, is_interrupted, pause_seconds)

            if previous is None:
                continue
            if is_interrupted:
                previous.set_pause(char.id, current_seconds)
                previous_to_delete[previous.id] = previous
                continue

            if char.id == self.first_character_id:
                on_finish = previous.plan.on_finish_first
            else:
                on_finish = 'break' if self.plan.is_break_second else previous.plan.on_finish_second

            if on_finish == 'next_stage':
                if previous.next_stage():
                    char.update(plan_data=previous)
                else:
                    previous.set_pause(char.id, current_seconds)
                    previous_to_delete[previous.id] = previous
            elif on_finish == 'break':
                previous.set_pause(char.id, current_seconds)
                previous_to_delete[previous.id] = previous
            else:  # ignore
                stage = previous.get_stage()
                if stage is not None:
                    char.update(plan_data=previous)

        for previous in previous_to_delete.values():
            previous.delete()
        self.delete()


class Stage(BaseModel):
    __is_initialized = False

    def __init__(self, pk):
        super(Stage, self).__init__(pk)
        if self.__is_initialized:
            return

        if self.filters_id and not self.filters.time_max_seconds:
            self.is_filter_stage = True
            for name in ('effects_id', 'filters_place_id', 'filters_plan_set_id', 'lock_id'):
                if getattr(self, name) is not None:
                    self.is_filter_stage = False
                    break
        else:
            self.is_filter_stage = False

        self.__is_initialized = True

    def __str__(self):
        if self.effects_id:
            effects = self.effects
            items = ['{}: '.format(effects.__class__.__name__)]
            if self.title:
                items.append(self.title)
                return ''.join(items)
            if effects.first_character_id and effects.second_character_id:
                items.append('{} > {}'.format(effects.first_character.title, effects.second_character.title))
            else:
                if effects.first_character_id:
                    items.append(effects.first_character.title)
                elif effects.second_character_id:
                    items.append('second: {}'.format(effects.second_character.title))
            if self.filters_plan_set_id:
                items.append(', changeable')
            if self.filters_id:
                items.append(', filtered')
            return ''.join(items)

        for attname in ['filters_place', 'lock', 'filters_plan_set', 'plan_pause', 'filters']:
            instance = getattr(self, attname)
            if not instance:
                continue
            return '{}: {}'.format(instance.__class__.__name__, self.title or instance.id)
        return 'empty'


class CharacterDataEffects(BaseModel):
    def __str__(self):
        return self.title or self.id


class CharacterDataFilters(BaseModel):
    __is_initialized = False
    is_relationships_base_own = False
    is_relationships_base_other = False
    is_relationships_mods_own = False
    is_relationships_mods_other = False
    is_relationships_plan_mods_own = False
    is_relationships_plan_mods_other = False

    def __init__(self, pk):
        super(CharacterDataFilters, self).__init__(pk)
        if self.__is_initialized:
            return

        self.acceptance_points_min = self.acceptance_points_min or 100
        self.acceptance_points_max = self.acceptance_points_max or 1000

        for data, name in [
            (self.acceptance_points_base, 'is_relationships_base'),
            (self.acceptance_points_mods, 'is_relationships_mods'),
            (self.plan_points_mods, 'is_relationships_plan_mods')
        ]:
            for pos_neg in data:
                pos_neg_value = data[pos_neg]
                for own_other in pos_neg_value:
                    own_another_value = pos_neg_value[own_other]
                    for attr_type in own_another_value:
                        attr_type_value = own_another_value[attr_type]
                        if attr_type == 'exact':
                            if attr_type_value == 'relationship':
                                setattr(self, '{}_{}'.format(name, own_other), True)
                                break
                        elif 'relationship' in attr_type_value:
                            setattr(self, '{}_{}'.format(name, own_other), True)
                            break

        self.__is_initialized = True

    def __str__(self):
        return self.title

    def get_acceptance_points(self, char_own, char_other):
        points = CharacterPlanModifiers(
            instance=char_own,
            points_mods=self.acceptance_points_base,
            char_other=char_other,
            is_relationships_own=self.is_relationships_base_own,
            is_relationships_other=self.is_relationships_base_other
        ).get()
        if self.acceptance_points_mods:
            points_mod = CharacterPlanModifiers(
                instance=char_own,
                points_mods=self.acceptance_points_mods,
                char_other=char_other,
                is_relationships_own=self.is_relationships_mods_own,
                is_relationships_other=self.is_relationships_mods_other
            ).get_mod(self.acceptance_points_mod_value)
            points = round(points * points_mod, 4)
        if points < 100:
            points = 100
        elif points > 1000:
            points = 1000
        if self.acceptance_points_max >= points >= self.acceptance_points_min:
            return points


class CharacterDataPlanFilters(BaseModel):
    def __str__(self):
        return self.title or str(self.id)


class PlanEffectsSet(BaseModel):
    __is_initialized = False
    orders = ('one', 'two', 'three', 'four', 'five')
    needs_mods_attrs = {'energy', 'sleep', 'mood', 'health'}

    def __init__(self, pk):
        super(PlanEffectsSet, self).__init__(pk)
        if self.__is_initialized:
            return

        needs_mods = {}
        effects = {}
        effects_max = {}
        settlement_effects = {}
        settlement_effects_max = {}
        place_settlement_effects = {}
        place_settlement_effects_max = {}
        effects_sep = []
        effects_replacements = {}
        relationships_effects = 0
        relationships_effects_min = 100
        relationships_effects_max = 1000

        for o in self.orders:
            data_effects = getattr(self, o)
            if not data_effects:
                continue
            if data_effects.effects_mods or data_effects.effects_place_mods:
                effects_sep.append(data_effects)
            else:
                for k, v in data_effects.effects.items():
                    if k in effects:
                        effects[k] += v
                    elif isinstance(v, (str, unicode)) and v.startswith('_'):
                        effects_replacements[k] = v
                    else:
                        effects[k] = v
                if data_effects.effects_max:
                    effects_max.update(data_effects.effects_max)
            for name, data in (
                ('settlement_effects', settlement_effects), ('place_settlement_effects', place_settlement_effects)
            ):
                data_effects_settlement = getattr(data_effects, name)
                for k in data_effects_settlement:
                    if k in data:
                        data[k] += data_effects_settlement[k]
                    else:
                        data[k] = data_effects_settlement[k]
            if data_effects.settlement_effects_max:
                settlement_effects_max.update(data_effects.settlement_effects_max)
            if data_effects.needs_mods:
                needs_mods.update(data_effects.needs_mods)
            if data_effects.relationships_effects:
                relationships_effects += data_effects.relationships_effects
                if data_effects.relationships_effects_min or data_effects.relationships_effects_max:
                    relationships_effects_min = data_effects.relationships_effects_min or 100
                    relationships_effects_max = data_effects.relationships_effects_max or 1000

        self.effects = effects
        self.effects_sep = effects_sep
        self.effects_replacements = effects_replacements
        self.effects_max = effects_max
        self.settlement_effects = settlement_effects
        self.settlement_effects_max = settlement_effects_max
        self.place_settlement_effects = place_settlement_effects
        self.place_settlement_effects_max = place_settlement_effects_max
        self.needs_mods = {mod_key: needs_mods.get(mod_key, 1) for mod_key in self.needs_mods_attrs}
        self.relationships_effects = relationships_effects
        self.relationships_effects_min = relationships_effects_min
        self.relationships_effects_max = relationships_effects_max
        self.__is_initialized = True

    def __str__(self):
        return self.title

    def get_effects(self, char, char_other=None, is_first=True):
        effects = dict(self.effects)

        for data in self.effects_sep:
            effects_mods = data.effects_mods
            effects_place_mods = data.effects_place_mods
            if effects_mods and effects_place_mods:
                mod = CharacterPlanModifiers(char, effects_mods, char_other).get_mod(data.effects_mods_value)
                mod += PlanModifiersPosNeg(char.place, effects_place_mods).get_mod()
                mod /= 2
            elif effects_mods:
                mod = CharacterPlanModifiers(char, effects_mods, char_other).get_mod(data.effects_mods_value)
            elif effects_place_mods:
                mod = PlanModifiersPosNeg(char.place, effects_place_mods).get_mod()
            else:
                mod = 1

            effects_item = {k: v * 1000 * mod / 1000 for k, v in data.effects.items()} if mod != 1 else data.effects
            for name in effects_item:
                if name in effects:
                    effects[name] += effects_item[name]
                else:
                    effects[name] = effects_item[name]

        for k, v in self.effects_replacements.items():
            if is_first:
                effects[k] = get_value_replaced_second_char(v, char, char_other)
            else:
                effects[k] = get_value_replaced_second_char(v, char_other, char)

        return effects


class PlanEffects(BaseModel):
    pass


class PlanFilters(BaseModel):
    def filter(self, first_character, second_character=None):
        for char_own, char_other, filters_data in (
            (first_character, second_character, self.first_character),
            (second_character, first_character, self.second_character)
        ):
            if char_own is None or filters_data is None:
                continue
            is_passed = True
            if filters_data.filters:
                is_passed = bool(Character.objects.filter(
                    id=char_own.id, **get_filters_replaced(filters_data.filters, char_own, char_other)
                ))
            if is_passed and filters_data.acceptance_points_base:
                is_passed = not filters_data.get_acceptance_points(char_own, char_other)
            if not is_passed:
                return False
        return True

    def __str__(self):
        items = []
        if self.first_character_id or self.second_character_id:
            items2 = []
            if self.first_character_id:
                items2.append('f: {}'.format(self.first_character.title or self.first_character_id))
            if self.second_character_id:
                items2.append('s: {}'.format(self.second_character.title or self.second_character_id))
            items.append(', '.join(items2))
        if self.time_from:
            items.append('from {}'.format(self.time_from))
        if self.time_to:
            items.append('to {}'.format(self.time_to))
        if self.time_min:
            items.append('min: {}'.format(self.time_min))
        if self.time_max:
            items.append('max: {}'.format(self.time_max))
        return ' '.join(items)


class PlanPlaceFilters(BaseModel):
    pass


class PlanSetFilters(BaseModel):
    pass


class PlanLock(BaseModel):
    pass


class PlanPause(BaseModel):
    pass


class Character(BaseModel):
    __is_initialized = False

    def __init__(self, pk):
        super(Character, self).__init__(pk)
        if self.__is_initialized:
            return

        self.full_name = ' '.join([self.first_name, self.last_name])
        self.say = renpy.character.Character(name=self.full_name, color=self.color_name, image=self.title)

        self.__is_initialized = True

    def __str__(self):
        return self.title

    def delete(self):
        super(Character, self).delete()
        self.place.update_population(-1)

    def clone(self, **kwargs):
        clone = super(Character, self).clone(is_original=False, **kwargs)
        clone.place.update_population(1)
        return clone

    def get_original(self):
        if self.is_original:
            return self
        return Character.objects.get(title=self.title, is_original=True)

    def get_opinion_obj(self, to_character_id):
        from_id = self.get_original().id
        key = '{}_{}'.format(from_id, to_character_id)
        obj = relations_cache.get(key)
        if not obj:
            obj = CharacterRelationship.objects.get(from_character_id=from_id, to_character_id=to_character_id)
            if not obj:
                to_character_id = Character(to_character_id).get_original().id
                obj = CharacterRelationship.objects.get(from_character_id=self.id, to_character_id=to_character_id)
            relations_cache[key] = obj
        return obj

    def get_opinion(self, to_character_id):
        return self.get_opinion_obj(to_character_id).value

    def update_opinion(self, to_character_id, value, min_value=100, max_value=1000):
        self.get_opinion_obj(to_character_id).update_relation(value, min_value, max_value)

    def change_place(self, new):
        self.place.update_population(-1)
        new.update_population(1)
        self.update(place=new)


class CharacterRelationship(BaseModel):
    def __str__(self):
        return '{} > {} = {}'.format(self.from_character.title, self.to_character.title, self.value)

    def update_relation(self, relation_change, min_value=100, max_value=1000):
        current_value = self.value
        if current_value > max_value:
            return
        if current_value < min_value:
            return
        new_value = current_value + relation_change
        if new_value > max_value:
            new_value = max_value
        elif new_value < min_value:
            new_value = min_value
        self.update(value=new_value)


class Faction(BaseModel):
    def __str__(self):
        return self.title


class FactionRelationship(BaseModel):
    def __str__(self):
        return '{} > {} = {}'.format(self.from_faction.title, self.to_faction.title, self.value)


# Place
class Place(BaseModel):
    def __str__(self):
        return self.title

    def update_population(self, value):
        self.update(population=self.population+value)

    def is_lock_filters_bypass(self, char, current_place_id):
        qs_filters = self.lock_filters
        if not qs_filters:
            return True
        if current_place_id:
            qs_filters = dict(qs_filters)
            for k in self.lock_filters:
                if k.startswith('place_id') and not k.endswith('__or'):
                    v = qs_filters.pop(k)
                    if isinstance(v, list):
                        if current_place_id not in v:
                            return False
                    elif current_place_id != v:
                        return False
        return char in Character.objects.filter(**qs_filters)

    def is_lock(self, char, current_place_id=None):
        if not self.is_locked:
            return False
        if self.lock_filters:
            return not self.is_lock_filters_bypass(char, current_place_id)
        return True


class PlaceTransition(BaseModel):
    def __str__(self):
        return '{} > {} = {} km'.format(self.from_place.title, self.to_place.title, self.distance)


# Place types
class Canteen(BaseModel):
    def __str__(self):
        return self.place.title


class HealerPost(BaseModel):
    def __str__(self):
        return '{} | {}'.format(self.place.title, self.owner.title)


class Home(BaseModel):
    def __str__(self):
        return '{} | {}'.format(self.place.title, self.owner.title)


class Prison(BaseModel):
    def __str__(self):
        return self.place.title


class PrisonCell(BaseModel):
    def __str__(self):
        return self.place.title


class Kitchen(BaseModel):
    def __str__(self):
        return self.place.title


class Region(BaseModel):
    def __str__(self):
        return self.place.title


class Street(BaseModel):
    def __str__(self):
        return self.place.title


class SettlementGates(BaseModel):
    def __str__(self):
        return self.place.title


class Temple(BaseModel):
    def __str__(self):
        return self.place.title


class TempleCabinActive(BaseModel):
    def __str__(self):
        return self.place.title


class TempleCabinPassive(BaseModel):
    def __str__(self):
        return self.place.title


class Route(BaseModel):
    is_targeted = False

    @classmethod
    def create(cls, transitions, **kwargs):
        if transitions is None:
            return

        if 'start_place' in kwargs:
            start_place = kwargs['start_place']
        elif 'start_place_id' in kwargs:
            start_place = Place(kwargs['start_place_id'])
        else:
            start_place = kwargs['first_character'].place
            kwargs['start_place'] = start_place

        route_distance = 0
        places = OrderedDict({0: start_place})
        for t in transitions:
            route_distance += t.distance * 1000
            places[route_distance / 1000] = t.to_place
        route_distance /= 1000

        instance = super(cls, cls).create(
            route_distance=route_distance, next_check=min(places), places=places, **kwargs
        )
        if DEBUG_SIMULATION or DEBUG_ROUTE_SEARCH:
            logger_simulation.info('new route for {}: {}'.format(instance.first_character, instance))
        return instance

    def __str__(self):
        if not self.places:
            return 'is finished'
        desc = ' - '.join(['{}({})'.format(v.title, k) for k, v in self.places.items()])
        if self.places:
            return desc
        return '{} - Finished'.format(desc)

    def get_last_place(self):
        return self.places[self.route_distance]

    def get_last_place_id(self):
        place = self.get_last_place()
        if place is not None:
            return place.id


# Settlements
class Settlement(BaseModel):
    def __str__(self):
        return self.title

    def set_positions(self):
        if DEBUG_SET_POSITIONS:
            logger_positions.info('Set positions for "{}"'.format(self.title))

        settlement_chars_qs = self.character_set.filter(id__ne=PLAYER_ID)
        settlement_chars_number = settlement_chars_qs.count()
        required_positions_number = defaultdict(int)
        positions = self.positions.filter().order_by('-value')

        for position in positions:
            number = ceil(settlement_chars_number * position.population_ratio) or position.min_number or 0
            max_number = position.max_number
            if max_number is not None and number > max_number:
                number = max_number
            required_positions_number[position.id] = number

        positions_chars_points = defaultdict(dict)
        for position in positions:
            points_mods = position.points_mods
            qs_filters = dict(position.character_filters)
            if position.title != 'unemployed':
                qs_filters['is_chained'] = False

            position_chars = settlement_chars_qs.filter(**qs_filters)
            if not position_chars:
                continue
            for char in position_chars:
                points = PlanModifiersPosNeg(char, points_mods).get() if points_mods else 100
                if char.position_id == position.id:
                    points += position.value / 5
                positions_chars_points[position.id][char.id] = points

            if position.is_voting:
                votes = {k: 0 for k in positions_chars_points[position.id]}
                for char in settlement_chars_qs.filter(id__nin=set(votes)):
                    rels = dict(CharacterRelationship.objects.filter(
                        from_character_id=char.id, to_character_id__in=set(votes)
                    ).values('to_character_id', 'value'))
                    votes[max(rels, key=rels.get)] += 1
                positions_chars_points[position.id][max(votes, key=votes.get)] *= 1.25

        chars_employed_ids = set()
        for position in positions:
            position_id = position.id
            if DEBUG_SET_POSITIONS:
                logger_positions.info('{} {}'.format(required_positions_number[position_id], position.title))
                logger_positions.info('*' * 10)
            while required_positions_number[position_id] > 0:
                position_points = positions_chars_points[position_id]
                while position_points:
                    char_id = max(position_points, key=position_points.get)
                    del position_points[char_id]
                    if char_id in chars_employed_ids:
                        continue
                    char = Character(char_id)
                    chars_employed_ids.add(char_id)
                    required_positions_number[position_id] -= 1
                    if DEBUG_SET_POSITIONS:
                        if char.is_chained:
                            add_info = ' (prisoner)'
                        elif char.position_id != position_id:
                            add_info = ' (new)'
                        else:
                            add_info = ''
                        logger_positions.info('{}{}'.format(char.title, add_info))
                    char.update(position_id=position_id)
                    break
                else:
                    break
            if DEBUG_SET_POSITIONS:
                logger_positions.info('*'*10)

        self.update(is_positions_set_required=False)


class SettlementPosition(BaseModel):
    def __str__(self):
        return self.name
