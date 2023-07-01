from __future__ import division

import itertools
import logging

from kernel.orm import QuerySet
from kernel.models import Plan
from kernel.settings import IDLE_PLAN_ID
from kernel.utils import dict_multiply


logger = logging.getLogger('simulation')


class PlanEffects(object):
    def __init__(self, stage, minutes_left, current_seconds, char, char_other=None, is_first=True):
        self.minutes_left = minutes_left
        self.current_seconds = current_seconds
        self.char = char
        self.char_other = char_other

        self.time_passed = 0
        self.is_finished = False
        self.is_interrupted = False
        self.is_first = is_first
        self.effects_update = {}

        filters = stage.filters
        if is_first:
            self.effects_data = stage.effects.first_character
            self.filters_data = filters.first_character if filters else None
        else:
            self.effects_data = stage.effects.second_character
            self.filters_data = filters.second_character if filters else None
        self.is_instant = stage.effects.is_instant or (self.effects_data and not filters)

        if not self.effects_data:
            plan = Plan(IDLE_PLAN_ID)
            self.effects_data = plan.two.effects.first_character
            self.filters_data = plan.two.filters.first_character

    def get_effects_instant(self):
        self.effects_update = self.effects_data.get_effects(self.char, self.char_other, self.is_first)
        update_max_effects(self.effects_update, self.effects_data.effects_max, self.char)
        self.is_finished = True

    def get_effects_timed(self):
        effects = self.effects_data.get_effects(self.char, self.char_other, self.is_first)

        time_passed = self.minutes_left
        effects_update = dict_multiply(effects, time_passed)
        update_max_effects(effects_update, self.effects_data.effects_max, self.char)

        if self.filters_data is not None:
            filters = self.filters_data.filters
            for attr_name in filters:
                relations, lookup, cmd = QuerySet.parse_filter(attr_name)
                if relations or lookup not in effects_update:
                    continue
                new_value = getattr(self.char, lookup) + effects_update[lookup]
                effect_value = filters[attr_name]

                if cmd == 'gt':
                    is_finished = new_value <= effect_value
                elif cmd == 'gte':
                    is_finished = new_value < effect_value
                elif cmd == 'lte':
                    is_finished = new_value > effect_value
                elif cmd == 'lt':
                    is_finished = new_value >= effect_value
                else:
                    is_finished = False

                if is_finished:
                    time_passed = round(abs((getattr(self.char, lookup) - effect_value) / effects[lookup]), 2)
                    effects_update = dict_multiply(effects, time_passed)
                    update_max_effects(effects_update, self.effects_data.effects_max, self.char)
                    self.is_finished = True
                    if self.filters_data.is_interrupting:
                        self.is_interrupted = True
                    break

        self.effects_update = effects_update
        self.time_passed = time_passed

    def run(self):
        if self.is_instant:
            self.get_effects_instant()
            return
        if self.minutes_left:
            self.get_effects_timed()
        # else waiting for instant second character

    def apply(self):
        if self.effects_update:
            apply_effects(self.char, self.effects_update)
            self.effects_update = {}

        time_passed = 1 if self.is_instant else self.time_passed

        apply_settlement_effects(self.char, self.effects_data, time_passed)

        relationships_effects = self.effects_data.relationships_effects
        if relationships_effects:
            if self.char.is_original:
                char_original = self.char
            else:
                char_original = self.char.objects.get(title=self.char.title, is_original=True)
            char_original.update_opinion(
                to_character_id=self.char_other.id,
                value=relationships_effects * time_passed,
                min_value=self.effects_data.relationships_effects_min,
                max_value=self.effects_data.relationships_effects_max
            )


def process_effects(stage, first_character, second_character, minutes_left, current_seconds, current_day_seconds):
    is_finished_minutes_left = False
    if stage.filters:
        time_to_seconds = stage.filters.time_to_seconds
        if time_to_seconds:
            if current_day_seconds > time_to_seconds:
                time_from_seconds = stage.filters.time_from_seconds
                if time_from_seconds and time_from_seconds > time_to_seconds:
                    seconds_left_max = time_to_seconds + 86400 - current_day_seconds
                else:
                    raise ValueError('Filters time range check function failed')
            else:
                seconds_left_max = time_to_seconds - current_day_seconds
            minutes_left_max = round(seconds_left_max / 60, 2)
            if minutes_left_max <= minutes_left:
                minutes_left = minutes_left_max
                is_finished_minutes_left = True

    if second_character:
        time_passed, is_interrupted, is_finished_effects = process_effects_group(
            stage, minutes_left, current_seconds, first_character, second_character
        )
    else:
        effects = PlanEffects(stage, minutes_left, current_seconds, first_character, None)
        effects.run()
        effects.apply()
        time_passed = effects.time_passed
        is_interrupted = effects.is_interrupted
        is_finished_effects = effects.is_finished
    return time_passed, is_interrupted, is_finished_minutes_left or is_finished_effects


def process_effects_group(stage, minutes_left, current_seconds, first_character, second_character):
    plan_effects = {first_character.id: None, second_character.id: None}
    time_passed = None
    for char, char_other, is_first in itertools.cycle((
        (first_character, second_character, True), (second_character, first_character, False)
    )):
        effects_progress = PlanEffects(
            stage, minutes_left if time_passed is None else time_passed, current_seconds, char, char_other, is_first
        )
        effects_progress.run()
        plan_effects[char.id] = effects_progress
        if effects_progress.time_passed == time_passed:
            break
        time_passed = effects_progress.time_passed

    for progress_data in plan_effects.values():
        progress_data.apply()

    first_effects = plan_effects[first_character.id]
    second_effects = plan_effects[second_character.id]
    time_passed = first_effects.time_passed
    is_interrupted = first_effects.is_interrupted or second_effects.is_interrupted
    is_finished = first_effects.is_finished or second_effects.is_finished
    return time_passed, is_interrupted, is_finished


def apply_effects(instance, data):
    instance.update(**{
        k: (getattr(instance, k) * 1000 + data[k] * 1000) / 1000
        if k in instance.objects_effects_fields else data[k] for k in data
    })


def apply_settlement_effects(char, effects_set, time_passed=None):
    for settlement, effects in (
        (char.settlement, effects_set.settlement_effects),
        (char.place.settlement if char.place is not None else None, effects_set.place_settlement_effects)
    ):
        if not effects or settlement is None:
            continue
        effects_timed = dict_multiply(effects, time_passed) if time_passed is not None else dict(effects)
        update_max_effects(effects_timed, effects_set.settlement_effects_max, settlement)
        apply_effects(settlement, effects_timed)


def update_max_effects(effects, effects_max, instance):
    for attr_name in effects_max:
        max_value = effects_max[attr_name]
        current_value = getattr(instance, attr_name)
        if current_value > max_value:
            del effects[attr_name]
        elif current_value + effects[attr_name] > max_value:
            effects[attr_name] = max_value - current_value


def update_natural_effects(character, time_passed, needs_mods=None):
    if needs_mods:
        energy_mod = needs_mods['energy']
        sleep_mod = needs_mods['sleep']
        mood_mod = needs_mods['mood']
        health_mod = needs_mods['health']
    else:
        energy_mod = 1
        sleep_mod = 1
        mood_mod = 1
        health_mod = 1

    effects = {}
    if sleep_mod:
        effects['sleep'] = -(0.7 * 1000 * sleep_mod / 1000)
    if energy_mod:
        effect = 0.35
        if character.sleep < 500:
            effect *= 1 + (500 - character.sleep) / 500
    if mood_mod:
        effects['mood'] = -(0.3 * 1000 * mood_mod / 1000)
    if health_mod:
        effects['health'] = 0.02 * 1000 * health_mod / 1000

    apply_effects(character, dict_multiply(effects, time_passed))


def process_natural(time_passed, first_character, second_character=None, effects_data=None):
    if not time_passed:
        return
    update_natural_effects(
        first_character, time_passed, effects_data.first_character.needs_mods if effects_data else None
    )
    if second_character:
        update_natural_effects(
            second_character, time_passed, effects_data.second_character.needs_mods if effects_data else None
        )
