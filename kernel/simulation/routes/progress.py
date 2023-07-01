import itertools
import logging
import random

from kernel.models import Plan
from kernel.settings import DEBUG_SIMULATION, IDLE_PLAN_ID, PLAYER_ID
from kernel.simulation.effects import update_max_effects, apply_settlement_effects, apply_effects
from kernel.simulation.plans.create import GetPlan
from kernel.simulation.plans.apply import set_plan
from kernel.simulation.routes.create import create_route
from kernel.utils import route_locked_places, dict_multiply, player_data

logger = logging.getLogger('simulation')


class RouteProgress(object):
    ENCOUNTER_PER_KM = 0.10
    IS_ROUTE_ENCOUNTERS = True

    def __init__(
        self,
        minutes_left,
        current_seconds,
        current_day_seconds,
        char,
        route=None,
        char_other=None,
        time_passed_other=0,
        filters_data=None,
        encounter_on=None
    ):
        self.minutes_left = minutes_left
        self.current_seconds = current_seconds
        self.current_day_seconds = current_day_seconds
        self.time_passed_other = time_passed_other
        self.filters_data = filters_data
        self.char = char
        self.char_other = char_other
        self.route = route
        self.encounter_on = encounter_on

        self.passed_places = []
        self.time_passed = 0
        self.time_waiting = 0
        self.plan_new = None
        self.plan_new_second_char = None
        self.route_update_data = None
        self.status = route.status if route else 'finished'
        self.char_id = char.id
        self.char_other_id = char_other.id if char_other else None
        self.second_character = self.route.second_character if self.route else None

    def __str__(self):
        if self.char_other_id:
            return 'f: {}, s: {}, {}'.format(self.char.title, self.char_other.title, self.status)
        return 'f: {}, {}'.format(self.char.title, self.status)

    def get_current_place(self):
        if self.passed_places:
            return self.passed_places[-1]
        return self.char.place

    def get_current_place_id(self):
        place = self.get_current_place()
        if place is not None:
            return place.id

    def is_finished(self):
        return self.status in ['not_found', 'finished']

    def route_progress(self, route):
        if route.route_distance == route.distance_passed:
            raise ValueError('Route is already finished')
        if route.first_character.is_chained:
            raise ValueError('Character is chained')

        # 100 meters per minute
        time_to_pass = (self.minutes_left * 1000 - self.time_passed * 1000) / 1000
        distance_time_left = round((route.route_distance - route.distance_passed) * 10, 4)
        if time_to_pass > distance_time_left:
            time_to_pass = distance_time_left

        next_distances = list(route.places)[1:]
        next_distances.append(None)
        distance_max = round(route.distance_passed + time_to_pass / 10, 4)

        if self.encounter_on:
            distance_encounter = self.encounter_on
        elif self.ENCOUNTER_PER_KM:
            distance_encounter = round(random.uniform(
                route.distance_passed, route.distance_passed + self.ENCOUNTER_PER_KM
            ), 3)
        else:
            distance_encounter = 99999
        is_encounter = False

        distance_passed = route.distance_passed
        for inx, place_distance in enumerate(route.places):
            if place_distance > distance_max:
                break
            distance_next = next_distances[inx]
            if distance_next is None:
                distance_passed = place_distance
                self.status = 'finished'
            elif route.distance_passed >= distance_next:
                continue
            elif distance_next > distance_max:
                distance_passed = distance_max
            else:
                distance_passed = distance_next

            place = route.places[place_distance]
            if place.is_lock(char=route.first_character, current_place_id=self.get_current_place_id()):
                self.status = 'locked'
                route_locked_places[self.char_id].add(place.id)
                distance_passed = max(place_distance, route.distance_passed)
            else:
                if route.distance_passed < distance_encounter < distance_passed:
                    if self.IS_ROUTE_ENCOUNTERS:
                        player_data['disable_plans_menu'] = True
                        is_encounter = True
                        qs_filters = {'is_route__or9': True, 'is_encounter__or9': True}
                    else:
                        qs_filters = {'is_encounter': True}
                elif self.IS_ROUTE_ENCOUNTERS:
                    qs_filters = {'is_route': True}
                else:
                    qs_filters = {}

                if qs_filters:
                    places_before = []  # plan search in this place
                    if self.char.place is not place:
                        for char in (self.char, self.second_character):
                            if not char:
                                continue
                            places_before.append((char.place, char))
                            char.change_place(place)
                    get_plan = GetPlan(self.current_seconds, self.current_day_seconds, self.char, qs_filters)
                    self.plan_new, self.plan_new_second_char = get_plan.get_plan()
                    if self.plan_new:
                        if self.plan_new.is_encounter:
                            distance_passed = distance_encounter
                        elif self.plan_new.is_route:
                            distance_passed = max([place_distance, route.distance_passed])
                        if DEBUG_SIMULATION:
                            logger.info('new plan while processing route')
                        self.status = 'finished'
                    elif distance_encounter < distance_passed:
                        distance_encounter = 99999
                    if is_encounter:
                        player_data['disable_plans_menu'] = False
                    for place_prev, char in places_before:
                        char.change_place(place_prev)

                if self.char.place is not place:
                    self.passed_places.append(place)

            self.time_passed = round((distance_passed - route.distance_passed) * 10, 4)
            if self.status != 'in_progress':
                break

        update_data = {'distance_passed': distance_passed, 'status': self.status}
        if self.status == 'finished':
            route_locked_places[self.char_id] = set()
            if DEBUG_SIMULATION:
                # can be seen twice if group route with waiting
                logger.info('finished route to {}'.format(self.get_current_place().title))
        elif self.status == 'locked':
            if DEBUG_SIMULATION:
                logger.info('{} is locked, stayed at {}'.format(
                    place.title, self.get_current_place().title  # noqa
                ))

        return update_data

    def progress(self):
        if self.status != 'in_progress':
            self.time_waiting = self.time_passed_other or self.minutes_left
            return
        self.route_update_data = self.route_progress(self.route)
        if self.status == 'locked' and not self.route.is_targeted:
            while self.time_passed < self.minutes_left:
                route, self.status = create_route(
                    self.filters_data, self.char, self.char_other, self.get_current_place()
                )
                if self.status in ['not_found', 'finished'] or not route:
                    self.route_update_data = None
                    return
                self.route_update_data = self.route_progress(route)
                if self.status != 'locked':
                    self.route = route
                    return

        if self.status in ['not_found', 'locked']:
            return
        if self.time_passed_other:
            self.time_waiting = round(self.time_passed_other - self.time_passed, 4)
            if self.time_waiting < 0:
                self.time_waiting = 0

    def apply(self):
        if self.route_update_data:
            self.route.update(**self.route_update_data)
            self.route_update_data = {}

        for char in (self.char, self.second_character):
            if char is None:
                continue
            if self.time_waiting:
                if DEBUG_SIMULATION:
                    logger.info('{} is waiting'.format(self.char.title))
                effects_set = Plan(IDLE_PLAN_ID).two.effects.first_character
                update_data = dict_multiply(effects_set.get_effects(self.char), self.time_waiting)
                update_max_effects(update_data, effects_set.effects_max, self.char)
                apply_settlement_effects(self.char, effects_set, self.time_waiting)
            else:
                update_data = {}
            if self.passed_places:
                current_place = self.get_current_place()
                update_data['place'] = current_place
                char.place.update_population(-1)
                current_place.update_population(1)
            if update_data:
                apply_effects(char, update_data)

        if self.plan_new:
            set_plan(
                plan=self.plan_new,
                first_character=self.char,
                current_seconds=self.current_seconds,
                second_character=self.plan_new_second_char,
                is_break=True
            )


def progress_group(f_char, f_route, s_char, s_route, filters_data, minutes_left, current_seconds, current_day_seconds):
    data = {f_char.id: None, s_char.id: None}
    time_passed = None
    minutes_left_progress = minutes_left

    for char, route in itertools.cycle([(f_char, f_route), (s_char, s_route)]):
        route_progress = RouteProgress(
            minutes_left=minutes_left_progress,
            current_seconds=current_seconds,
            current_day_seconds=current_day_seconds,
            char=char,
            route=route,
            char_other=s_char if char is f_char else f_char,
            time_passed_other=time_passed or 0,
            filters_data=filters_data
        )
        route_progress.progress()
        time_passed_current = route_progress.time_passed + route_progress.time_waiting
        data[char.id] = route_progress
        if time_passed_current == time_passed:
            break
        if route and route.second_character_id:
            data[(f_char if char is s_char else s_char).id] = route_progress
            break
        if route_progress.status != 'finished' or char.id == PLAYER_ID:
            minutes_left_progress = time_passed_current
        time_passed = time_passed_current

    f_progress = data[f_char.id]
    s_progress = data[s_char.id]
    for progress in (f_progress, s_progress):
        progress.apply()
        if progress.route and progress.route.second_character_id:  # same route
            break

    return f_progress, s_progress


def route_single_plan(stage, current_seconds, current_day_seconds, first_character, minutes_left):
    plan_data = first_character.plan_data
    progress = RouteProgress(
        minutes_left=minutes_left,
        current_seconds=current_seconds,
        current_day_seconds=current_day_seconds,
        char=first_character,
        route=plan_data.first_route,
        filters_data=stage.filters_place
    )
    progress.progress()
    progress.apply()
    if progress.plan_new:
        return progress.time_passed

    if progress.status == 'finished':
        if first_character.id != PLAYER_ID or (
            len(player_data['suitable_places']) == 1 and first_character.place in player_data['suitable_places']
        ):
            if not plan_data.next_stage():
                plan_data.finish_plan(current_seconds)
            plan_data.update(first_route=None)
        elif first_character.id == PLAYER_ID:
            player_data['is_break_simulation'] = True
    elif progress.status in ['not_found', 'locked']:
        plan_data.finish_plan(current_seconds, True)
        plan_data.update(first_route=None)
    elif plan_data.first_route is not progress.route:
        plan_data.update(first_route=progress.route)
    return progress.time_passed


def route_group_plan(stage, current_seconds, current_day_seconds, first_character, second_character, minutes_left):
    plan_data = first_character.plan_data
    f_progress, s_progress = progress_group(
        f_char=first_character,
        f_route=plan_data.first_route,
        s_char=second_character,
        s_route=plan_data.second_route,
        filters_data=stage.filters_place,
        minutes_left=minutes_left,
        current_seconds=current_seconds,
        current_day_seconds=current_day_seconds
    )
    time_passed = f_progress.time_passed + f_progress.time_waiting
    if f_progress.plan_new:
        return time_passed

    if f_progress.status == 'finished' and s_progress.status == 'finished':
        if first_character.id != PLAYER_ID or (
            len(player_data['suitable_places']) == 1 and first_character.place in player_data['suitable_places']
        ):
            if not plan_data.next_stage():
                plan_data.finish_plan(current_seconds)
            plan_data.update(first_route=None, second_route=None)
        elif first_character.id == PLAYER_ID:
            player_data['is_break_simulation'] = True
    elif {f_progress.status, s_progress.status} & {'locked', 'not_found'}:
        logger.info('route not found or locked')
        plan_data.finish_plan(current_seconds, is_interrupted=True)
        plan_data.update(first_route=None, second_route=None)
    else:
        update_data = {
            k: progress.route for k, plan_data_route, progress, char in (
                ('first_route', plan_data.first_route, f_progress, first_character),
                ('second_route', plan_data.second_route, s_progress, second_character)
            ) if plan_data_route is not progress.route and progress.char is char
        }
        if update_data:
            plan_data.update(**update_data)
        if (
            first_character.id == PLAYER_ID and
            f_progress.status == 'finished' and
            first_character.place not in player_data['suitable_places']  # wait for second
        ):
            player_data['is_break_simulation'] = True

    return time_passed
