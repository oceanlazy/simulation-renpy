from __future__ import division

import logging
import random

from kernel.models import Character, Plan
from kernel.settings import DEBUG_SIMULATION
from kernel.utils import stay_until_seconds, plan_pauses

logger = logging.getLogger('simulation')


def process_pause(char_id, stage_filters, period_minutes_left, current_seconds):
    seconds_until = stay_until_seconds[char_id]
    if not seconds_until:
        seconds_until = round(current_seconds + random.randint(
            stage_filters.time_min_seconds or 0, stage_filters.time_max_seconds
        ))
        if DEBUG_SIMULATION:
            logger.info('{} stay for {} minutes({} seconds)'.format(
                Character(char_id).title, round((seconds_until - current_seconds) / 60, 2), seconds_until
            ))
        stay_until_seconds[char_id] = seconds_until
    time_passed = 0
    if seconds_until > current_seconds:
        time_passed = round((seconds_until - current_seconds) / 60, 4)
        if time_passed > period_minutes_left:
            time_passed = period_minutes_left
            if DEBUG_SIMULATION:
                minutes = max(round(((seconds_until - current_seconds) / 60 * 100 - 3.0 * 100) / 100, 2), 0)
                logger.info('{} minutes left'.format(minutes))
    if not time_passed:
        stay_until_seconds[char_id] = 0
        return False
    return time_passed


def set_plan_pauses(plan_pause, first_character_id, current_seconds, second_character_id=None):
    for char_id, data in ((first_character_id, plan_pause.first), (second_character_id, plan_pause.second)):
        if not char_id or not data:
            continue
        for title, pause in data.items():
            plan = Plan.objects.get(title=title)
            plan_pauses[char_id][plan.id] = -1 if pause == -1 else round(current_seconds + pause * 60, 2)
            if DEBUG_SIMULATION:
                logger.info('set pause for {}({}) until {}'.format(
                    plan.title, Character(char_id).title, plan_pauses[char_id][plan.id]
                ))


def get_plan_pause(plan_id, char_id, current_seconds, is_log=True):
    char_pauses = plan_pauses[char_id]
    if not char_pauses:
        return False
    seconds_until = char_pauses[plan_id]
    if not seconds_until:
        return False
    if seconds_until > current_seconds or seconds_until == -1:
        if DEBUG_SIMULATION and is_log:
            title = Plan(plan_id).title
            if seconds_until > current_seconds:
                logger.info('{} paused for {} seconds'.format(title, seconds_until - current_seconds))
            else:
                logger.info('{} is disabled by pause seconds'.format(title))
        return True
    else:
        plan_pauses[char_id][plan_id] = 0
        return False
