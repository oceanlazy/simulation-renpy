from __future__ import division

import logging

from datetime import timedelta

from kernel import renpy
from kernel.models import Character, Plan, Settlement
from kernel.settings import DEBUG_SIMULATION, DEBUG_ORM, PLAYER_ID, START_DT, SIMULATE_PERIOD
from kernel.simulation.base import SimulationPeriod
from kernel.simulation.plans.apply import get_and_set_plan, set_plan
from kernel.utils import group_times, player_data

logger_simulation = logging.getLogger('simulation')
logger_orm = logging.getLogger('orm')


class Time(object):
    def __init__(self, start_dt):
        self.dt = start_dt
        self.seconds = start_dt.hour * 3600 + start_dt.minute * 60 + start_dt.second

    def add_seconds(self, seconds):
        self.dt += timedelta(seconds=seconds)
        self.seconds += seconds

    def get_day_seconds(self):
        return self.dt.hour * 3600 + self.dt.minute * 60 + self.dt.second


class Simulation(object):
    time = Time(START_DT)

    def __init__(self):
        for s in Settlement.objects.filter():
            s.set_positions()

    def simulate(self, **time_kwargs):
        simulate_to_seconds = self.time.seconds + timedelta(**time_kwargs or {'minutes': 99999}).total_seconds()
        period_seconds = SIMULATE_PERIOD.total_seconds()
        period_minutes = round(period_seconds / 60, 2)
        player = Character(PLAYER_ID)
        initial_plan_data = player.plan_data
        chars = [player]
        chars.extend(Character.objects.filter(is_clone=False, id__ne=PLAYER_ID))

        while self.time.seconds < simulate_to_seconds:
            if DEBUG_SIMULATION:
                logger_simulation.info(
                    '{} {}({}) {}'.format('*' * 10, self.time.dt, self.time.seconds, '*' * 10)
                )
                for s in Settlement.objects.filter():
                    logger_simulation.info('{}:, g: {}'.format(s.title, s.gold))

            if self.time.seconds + period_seconds >= simulate_to_seconds:
                if initial_plan_data and player.plan_data and player.plan_data is not initial_plan_data:
                    simulate_to_seconds += period_seconds + group_times[PLAYER_ID] * 60
                if self.time.seconds + period_seconds > simulate_to_seconds:
                    period_seconds = (simulate_to_seconds * 1000 - self.time.seconds * 1000) / 1000
                    period_minutes = round(period_seconds / 60, 2)

            for char in chars:
                if DEBUG_SIMULATION:
                    plan_data = char.plan_data
                    if plan_data:
                        first_character = plan_data.first_character
                        second_character = plan_data.second_character
                        plan_desc_items = [plan_data.plan.title]
                        if second_character is not None:
                            plan_desc_items.append('({})'.format(
                                second_character.title if first_character.id == char.id else first_character.title
                            ))
                        plan_desc = ''.join(plan_desc_items)
                    else:
                        plan_desc = 'no plan'
                    logger_simulation.info(
                        '--- {}({}, {}, g: {}, e: {}, sl: {}, h: {})'.format(
                            char.title.upper(),
                            char.place.title,
                            plan_desc,
                            int(char.gold),
                            int(char.energy),
                            int(char.sleep),
                            int(char.health),
                        )
                    )

                time_passed = 0
                current_seconds = self.time.seconds
                current_day_seconds = self.time.get_day_seconds()
                minutes_left = period_minutes

                group_time_passed = group_times[char.id]
                if group_time_passed:
                    if group_time_passed > period_minutes:
                        group_times[char.id] = group_time_passed - period_minutes
                        group_time_passed = period_minutes
                    else:
                        group_times[char.id] = 0
                    current_seconds += group_time_passed * 60
                    current_day_seconds += group_time_passed * 60
                    if current_day_seconds > 86400:
                        current_day_seconds = current_day_seconds - 86400
                    minutes_left = (minutes_left * 1000 - group_time_passed * 1000) / 1000
                    if not minutes_left:
                        time_passed = None
                    if DEBUG_SIMULATION:
                        logger_simulation.info('group time passed: {}'.format(group_time_passed))

                while time_passed is not None:
                    plan_data = char.plan_data
                    if char.id == PLAYER_ID:
                        if char.health < 101:
                            renpy.exports.say(None, "Lost health.")
                            renpy.exports.jump('game_over')
                            return
                        if char.energy < 101 and (not plan_data or plan_data.plan.title != 'fainting'):
                            set_plan(Plan.objects.get(title='fainting'), char, current_seconds, is_break=True)
                            plan_data = char.plan_data
                            player_data['is_restart_simulation'] = True
                        if not plan_data and not initial_plan_data:
                            time_passed = None
                            continue
                        if (not plan_data and initial_plan_data) or player_data['is_break_simulation']:
                            player_data['is_break_simulation'] = False
                            if not (plan_data and plan_data.plan.is_encounter):  # noqa
                                simulate_to_seconds = current_seconds
                                period_minutes = round(period_minutes - minutes_left, 2)
                                period_seconds = period_minutes * 60
                            break
                    elif plan_data is None:
                        get_and_set_plan(current_seconds, current_day_seconds, char)
                        continue
                    time_passed = SimulationPeriod(
                        char, period_minutes, minutes_left, current_seconds, current_day_seconds
                    ).simulate()
                    if not time_passed:
                        continue
                    if time_passed < 0:
                        raise ValueError('time_passed: {} less then zero'.format(time_passed))
                    elif time_passed > period_minutes:
                        raise ValueError('time_passed: {} > period_minutes: {}'.format(time_passed, period_minutes))
                    if DEBUG_SIMULATION:
                        logger_simulation.info('time passed: {}'.format(round(time_passed, 2)))
                    current_seconds += time_passed * 60
                    current_day_seconds += time_passed * 60
                    if current_day_seconds > 86400:
                        current_day_seconds = current_day_seconds - 86400
                    minutes_left = (minutes_left * 1000 - time_passed * 1000) / 1000

            if period_seconds:
                self.time.add_seconds(period_seconds)
            if player_data['is_restart_simulation']:
                player_data['is_restart_simulation'] = False
                period_seconds = SIMULATE_PERIOD.total_seconds()
                period_minutes = round(period_seconds / 60, 2)
                simulate_to_seconds += period_seconds

        if DEBUG_SIMULATION:
            logger_simulation.info('{} {}({}) {}'.format('*' * 10, self.time.dt, self.time.seconds, '*' * 10))
        if DEBUG_ORM:
            from kernel.utils import called_qs, called_qs_cache, qs_stat
            called_times = {k: (v, called_qs_cache[k], sum(qs_stat[k])) for k, v in called_qs.items()}
            called_times = sorted(called_times.items(), key=lambda v: sum(v[1]), reverse=True)
            for row in called_times:
                logger_orm.info(row)
