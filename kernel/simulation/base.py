from __future__ import division

import logging

from kernel.models import Place
from kernel.settings import DEBUG_SIMULATION
from kernel.simulation.pauses import process_pause, set_plan_pauses
from kernel.simulation.plans.apply import set_plan_single, set_plan_group
from kernel.simulation.routes.progress import route_single_plan, route_group_plan
from kernel.simulation.routes.create import create_route_plan
from kernel.simulation.effects import process_effects, process_natural
from kernel.utils import stay_until_seconds, get_filters_replaced, group_times, is_in_time_range, player_data

logger = logging.getLogger('simulation')


class SimulationPeriod(object):
    minutes_left = None
    is_finished = False
    is_interrupted = False
    plan_data = None
    first_character_id = None
    second_character_id = None
    first_character = None
    second_character = None

    def __init__(self, char, period_minutes, period_minutes_left, current_seconds, current_day_seconds):
        self.stage = None
        self.is_first = True
        self.current_seconds = current_seconds
        self.current_day_seconds = current_day_seconds
        self.period_minutes = period_minutes
        self.minutes_left = period_minutes_left
        self.char = char
        self.char_id = char.id
        self.plan_data = char.plan_data
        self.first_character = self.plan_data.first_character
        self.first_character_id = self.first_character.id
        self.second_character = self.plan_data.second_character
        self.second_character_id = self.second_character.id if self.second_character else None
        self.char_other = self.second_character if self.char_id == self.first_character_id else self.first_character
        self.char_other_id = self.char_other.id if self.char_other else None

    def __str__(self):
        return '{}: {}'.format(self.char.title, self.plan_data.plan or 'no plan')

    def lock_stage(self):
        lock_item = self.stage.lock
        for name, is_locked in (('close_filters', True), ('open_filters', False)):
            filters = getattr(lock_item, name)
            if not filters:
                continue
            place = Place.objects.get(**get_filters_replaced(filters, self.first_character, self.second_character))
            if not place:
                continue
            place.update(is_locked=is_locked)
            if DEBUG_SIMULATION:
                logger.info('{} was {} by {}'.format(
                    place.title, 'locked' if is_locked else 'unlocked', self.first_character.title
                ))

    def check_stage_finished(self):
        if self.minutes_left <= 0.01:
            if self.stage.effects_id:
                if self.stage.filters_id:
                    return True
                return False
            if self.stage.filters_plan_set_id:
                return False
            if self.stage.lock_id:
                return False
            if self.stage.plan_pause_id:
                return False
            if (
                self.stage.is_filter_stage and
                (not self.stage.filters.time_min_seconds and not self.stage.filters.time_max_seconds)
            ):
                return False
            return True
        if player_data['is_break_simulation']:
            return True
        return False

    def set_plan_filters(self):
        if self.second_character_id:
            return set_plan_group(
                self.stage, self.current_seconds, self.current_day_seconds, self.first_character, self.second_character
            )
        return set_plan_single(self.stage, self.current_seconds, self.current_day_seconds, self.first_character)

    def process_effects(self):
        time_passed, self.is_interrupted, self.is_finished = process_effects(
            stage=self.stage,
            first_character=self.first_character,
            second_character=self.second_character,
            minutes_left=self.minutes_left,
            current_seconds=self.current_seconds,
            current_day_seconds=self.current_day_seconds
        )
        return time_passed

    def process_route(self):
        if self.second_character_id:
            return route_group_plan(
                stage=self.stage,
                current_seconds=self.current_seconds,
                current_day_seconds=self.current_day_seconds,
                first_character=self.first_character,
                second_character=self.second_character,
                minutes_left=self.minutes_left
            )
        return route_single_plan(
            stage=self.stage,
            current_seconds=self.current_seconds,
            current_day_seconds=self.current_day_seconds,
            first_character=self.first_character,
            minutes_left=self.minutes_left
        )

    def next_stage(self):
        if not self.plan_data.next_stage():
            self.finish_plan()

    def finish_plan(self, is_interrupted=False, pause_seconds=None):
        self.plan_data.finish_plan(self.current_seconds, is_interrupted, pause_seconds)

    def simulate(self):
        stage = getattr(self.plan_data.plan, self.plan_data.plan_stage)
        self.stage = stage
        time_passed = None

        if self.check_stage_finished():
            return
        if DEBUG_SIMULATION:
            logger.info('stage {}'.format(stage))

        stage_filters = stage.filters
        is_time_filters = False
        if stage_filters:
            is_finished = False
            if stage_filters.time_max_seconds:
                is_time_filters = True
                time_passed = process_pause(
                    self.first_character_id, stage_filters, self.minutes_left, self.current_seconds
                )
                if time_passed is False:
                    is_finished = True
            if (
                is_finished or
                not is_in_time_range(self.current_day_seconds, stage_filters) or
                not stage_filters.filter(self.first_character, self.second_character)
            ):
                if DEBUG_SIMULATION and not stage.is_optional:
                    logger.info('filters not passed')
                if not stage.is_filter_stage or stage.is_optional:
                    self.next_stage()
                else:
                    self.finish_plan()
                return time_passed
            elif stage.is_filter_stage:
                self.next_stage()
                return 0

        if stage.filters_plan_set_id and self.set_plan_filters():
            stay_until_seconds[self.first_character_id] = 0
            return 0

        if stage.effects_id:
            time_passed = self.process_effects()
            if self.is_interrupted:
                self.finish_plan(is_interrupted=True)
            elif self.is_finished or time_passed < self.minutes_left:
                self.next_stage()
        elif stage.filters_place_id and not is_time_filters:
            if self.plan_data.first_route_id or self.plan_data.second_route_id:
                time_passed = self.process_route()
            else:
                create_route_plan(
                    stage, self.plan_data, self.current_seconds, self.first_character, self.second_character
                )
                time_passed = 0
        elif stage.lock_id and not is_time_filters:
            self.lock_stage()
            self.next_stage()
            time_passed = 0
        elif stage.plan_pause_id and not is_time_filters:
            set_plan_pauses(stage.plan_pause, self.first_character_id, self.current_seconds, self.second_character_id)
            self.next_stage()
            time_passed = 0

        process_natural(time_passed, self.first_character, self.second_character, stage.effects)
        if (
            self.second_character_id and
            time_passed and
            not (self.first_character.is_clone or self.second_character.is_clone)
        ):
            group_times[self.char_other_id] += time_passed
        elif time_passed is None:
            raise ValueError('Time not passed')
        if time_passed < 0:
            raise ValueError('time_passed: {} less then zero'.format(time_passed))
        if time_passed > self.period_minutes:
            raise ValueError('time_passed: {} > period_minutes: {}'.format(time_passed, self.period_minutes))

        return time_passed
