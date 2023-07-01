import random
import sys

from operator import itemgetter
from kernel import renpy
from kernel.models import Character, CharacterRelationship, FactionRelationship, Plan
from kernel.settings import PLAYER_ID
from kernel.simulation.pauses import get_plan_pause
from kernel.simulation.plans.modifiers import CharacterPlanModifiers
from kernel.utils import (
    ReplacementText,
    get_filters_replaced,
    get_value_replaced_second_char,
    is_in_time_range,
    player_data
)


def random_choice_weights_py3(points):
    return random.choices(points, weights=points)[0]


def random_choice_weights_py2(points):
    weights = [(p, p / 10) for p in points]
    return random.choice(*[[v] * w for v, w in weights])[0]


random_choice_weights = random_choice_weights_py2 if sys.version_info[0] < 3 else random_choice_weights_py3


class GetPlan(object):
    def __init__(
        self,
        current_seconds,
        current_day_seconds,
        char,
        filters=None,
        is_random_weighted=False,
        char_other=None
    ):
        self.current_seconds = current_seconds
        self.current_day_seconds = current_day_seconds
        self.char = char
        self.char_id = char.id
        self.char_other = char_other
        self.char_other_id = char_other.id if char_other else None
        self.filters = filters or {'is_char_available': True}
        self.is_random_weighted = is_random_weighted
        self.is_player = char.id == PLAYER_ID

    def _get_second_char(self, filters_second, plan, filters_first=None):
        char = self.char
        qs_filters = get_filters_replaced(filters_second.filters, char, self.char_other)
        second_chars = Character.objects.filter(**qs_filters).instances
        second_chars = [
            char for char in second_chars
            if not get_plan_pause(plan.id, char.id, self.current_seconds, is_log=False) and char.id != self.char_id
        ]
        if not second_chars:
            return

        for filters_, from_key, to_key in (
            (filters_first, 'from_faction_id', 'to_faction_id'), (filters_second, 'to_faction_id', 'from_faction_id')
        ):
            if not filters_:
                continue
            faction_opinion_max = filters_.faction_opinion_max
            faction_opinion_min = filters_.faction_opinion_min
            if faction_opinion_max or faction_opinion_min:
                qs_filters = {
                    from_key: char.faction_id, '{}__in'.format(to_key): {char.faction_id for char in second_chars}
                }
                if faction_opinion_max:
                    qs_filters['value__lte'] = faction_opinion_max
                if faction_opinion_min:
                    qs_filters['value__gte'] = faction_opinion_min
                qs = FactionRelationship.objects.filter(**qs_filters)
                if not qs:
                    return
                factions_ids = qs.values_list(to_key)
                second_chars = [char for char in second_chars if char.faction_id in factions_ids]
                if not second_chars:
                    return

        for filters_, from_key, to_key in (
            (filters_first, 'from_character_id', 'to_character_id'),
            (filters_second, 'to_character_id', 'from_character_id')
        ):
            if not filters_:
                continue
            relationships_max = filters_.relationships_max
            relationships_min = filters_.relationships_min
            if not relationships_max and not relationships_min:
                continue
            qs_filters = {  # noqa
                from_key: self.char_id, '{}__in'.format(to_key): {char.get_original().id for char in second_chars}
            }
            if relationships_max:
                qs_filters['value__lte'] = relationships_max
            if relationships_min:
                qs_filters['value__gte'] = relationships_min
            qs = CharacterRelationship.objects.filter(**qs_filters)
            if not qs:
                return
            second_chars = qs.values_list(to_key[:-3])

        second_chars_accepted = [(0, second_char) for second_char in second_chars]
        for filters_data in (filters_first, filters_second):
            if not filters_data or not filters_data.acceptance_points_base:
                continue
            temp = []
            for points_current, second_char in second_chars_accepted:
                if filters_data is filters_first:
                    points = filters_data.get_acceptance_points(char, second_char)
                else:
                    points = filters_data.get_acceptance_points(second_char, char)
                if not points:
                    continue
                temp.append(((points+points_current)/2 if points_current else points, second_char))
            if not temp:
                return
            second_chars_accepted = temp

        if self.is_player and not player_data['is_plans_not_found'] and not player_data['disable_plans_menu']:
            return [char for points, char in second_chars_accepted] if second_chars_accepted else second_chars
        second_char = max(second_chars_accepted, key=itemgetter(0))[1] if second_chars_accepted else second_chars[0]

        if second_char.id == PLAYER_ID and plan.is_ask_player:
            renpy.exports.show(' '.join([self.char.title, 'full']))
            renpy.exports.say(None, plan.get_ask_player_description(
                ReplacementText(self.char, second_char, self.char.place)
            ), interact=False)
            if renpy.exports.display_menu(
                [('Accept', 'accept'), ('Cancel', 'cancel')], screen='choice_yesno'
            ) == 'cancel':
                if second_chars_accepted is None:
                    second_char = second_chars[1] if len(second_chars) > 1 else None
                else:
                    del second_chars_accepted[0]
                    if second_chars_accepted:
                        second_char = max(second_chars_accepted, key=itemgetter(0))[1]
                    else:
                        second_char = None
            else:
                player_data['is_restart_simulation'] = True
                player_data['suitable_places'] = []
            renpy.exports.hide(' '.join([self.char.title, 'full']))

        return second_char

    def get_plan(self):
        options_points = {}

        for plan in Plan.objects.filter(**self.filters):
            if get_plan_pause(plan.id, self.char_id, self.current_seconds):
                continue

            filters = plan.filters
            min_points = plan.min_points
            if not filters:
                options_points[min_points] = (plan, None)
                continue

            time_from_seconds = filters.time_from_seconds
            time_to_seconds = filters.time_to_seconds
            if not is_in_time_range(self.current_day_seconds, filters):
                continue

            filters_first = filters.first_character
            if filters_first:
                filters_first_filters = filters_first.filters
                if filters_first_filters:
                    qs_filters = get_filters_replaced(
                        filters_first_filters, self.char, self.char_other
                    )
                    if 'id' in filters_first_filters:
                        if get_value_replaced_second_char(
                                filters_first_filters['id'], self.char, self.char_other
                        ) != self.char_id:
                            continue
                    else:
                        qs_filters['id'] = self.char_id
                    if not Character.objects.filter(**qs_filters):
                        continue

            if filters.second_character:
                second_character = self._get_second_char(filters.second_character, plan, filters_first)
                if not second_character:
                    continue
            else:
                second_character = None

            if filters_first and filters_first.plan_points_mods and (not self.is_player or not second_character):
                mod = CharacterPlanModifiers(
                    instance=self.char,
                    points_mods=filters_first.plan_points_mods,
                    char_other=second_character,
                    is_relationships_own=filters_first.is_relationships_plan_mods_own,
                    is_relationships_other=filters_first.is_relationships_plan_mods_other,
                ).get_mod()
                points = min_points * mod
            else:
                points = min_points
            if points < min_points:
                points = min_points

            if time_from_seconds and time_to_seconds and filters.is_time_points:
                seconds_check = self.current_day_seconds
                if time_from_seconds > time_to_seconds:
                    time_to_seconds_next_day = time_to_seconds + 86400
                    if seconds_check < time_to_seconds:
                        seconds_check += 86400
                else:
                    time_to_seconds_next_day = time_to_seconds
                seconds_optimal = (time_from_seconds + time_to_seconds_next_day) / 2
                if seconds_check > seconds_optimal:
                    points_time_modifier = seconds_optimal / seconds_check
                else:
                    points_time_modifier = seconds_check / seconds_optimal
                if time_from_seconds <= seconds_check <= time_to_seconds_next_day:
                    points_time_modifier += points_time_modifier / 2
                points *= points_time_modifier

            if points <= 100:
                continue
            if points in options_points:
                points += random.uniform(-.0000001, .0000001)
            options_points[points] = (plan, second_character)

        if not options_points:
            if self.is_player and player_data['is_choose_plan']:
                player_data['is_choose_plan'] = False
                player_data['is_plans_not_found'] = True
            return None, None
        if self.is_player and not player_data['is_plans_not_found'] and not player_data['disable_plans_menu']:
            choices = []
            for points in sorted(options_points, reverse=True):
                plan, second_characters = options_points[points]
                choices.append((plan.name, (plan, second_characters)))
            choice = renpy.store.generate_menu(choices)
            if choice == 'cancel':
                return None, None
            plan, choice_second_characters = choice
            if choice_second_characters:
                second_character = renpy.store.generate_menu(choice_second_characters, attr_name='full_name')
                if second_character == 'cancel':
                    return None, None
            else:
                second_character = None
            return plan, second_character
        if self.is_random_weighted:
            return options_points[random_choice_weights(list(options_points))]
        return options_points[max(options_points)]
