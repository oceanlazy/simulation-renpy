import logging

from kernel import renpy
from kernel.settings import DEBUG_SIMULATION
from kernel.models import EventLog, PlanData, Plan
from kernel.settings import IDLE_PLAN_ID, PLAYER_ID
from kernel.simulation.plans.create import GetPlan
from kernel.utils import ReplacementText

logger = logging.getLogger('simulation')


def get_and_set_plan(current_seconds, current_day_seconds, char, char_other=None, plan_filters=None, is_break=False):
    get_plan = GetPlan(
        current_seconds=current_seconds,
        current_day_seconds=current_day_seconds,
        char=char,
        filters=plan_filters.filters if plan_filters else None,
        is_random_weighted=plan_filters.is_random_weighted if plan_filters else False,
        char_other=char_other
    )
    plan, char_other = get_plan.get_plan()
    if not plan:
        if plan_filters:
            return False
        plan_data = PlanData.create(plan=Plan(IDLE_PLAN_ID), plan_stage='two', first_character=char)
        char.update(plan_data=plan_data)
        if DEBUG_SIMULATION:
            logger.info('plans not found, set plan to {}'.format(Plan(IDLE_PLAN_ID).title))
        return True
    set_plan(plan, char, current_seconds, char_other, is_break)
    return True


def set_plan(plan, first_character, current_seconds, second_character=None, is_break=False, is_interaction=True):
    plan_data_data = {'plan': plan, 'plan_stage': 'one', 'first_character': first_character}
    if second_character and plan.filters and plan.filters.is_group:
        if second_character.is_clone and second_character.is_original:
            if second_character.place_id:
                second_character = second_character.clone()
            else:
                second_character = second_character.clone(place_id=first_character.place_id)
        plan_data_data['second_character'] = second_character
        second_plan_data = second_character.plan_data
    else:
        second_character = None
        second_plan_data = None

    first_plan_data = first_character.plan_data
    if first_plan_data is second_plan_data:
        if first_plan_data:
            plan_data_data['first_previous'] = first_plan_data if first_character.id != PLAYER_ID else None
            plan_data_data['second_previous'] = second_plan_data if second_character.id != PLAYER_ID else None
    else:
        if first_plan_data:
            if is_break:
                first_plan_data.finish_plan(current_seconds, is_interrupted=True)
            elif first_plan_data.second_character_id:
                if not first_plan_data.next_stage():
                    first_plan_data.finish_plan(current_seconds)
            elif first_character.id != PLAYER_ID:
                plan_data_data['first_previous'] = first_plan_data
        if second_plan_data:
            if is_break or second_plan_data.second_character_id:
                second_plan_data.finish_plan(current_seconds, is_interrupted=is_break)
            elif second_character.id != PLAYER_ID:
                plan_data_data['second_previous'] = second_plan_data

    plan_data = PlanData.create(**plan_data_data)
    first_character.update(plan_data=plan_data)
    if second_character is not None:
        second_character.update(plan_data=plan_data)

    if not plan.is_ignore_event:
        EventLog.create_from_plan_data(current_seconds, plan_data)
    if (
        is_interaction and (
            (first_character and first_character.id == PLAYER_ID) or
            (second_character and second_character.id == PLAYER_ID)
        )
    ):
        callback = getattr(renpy.store, 'begin_{}'.format(plan.title), None)
        if callback:
            callback(plan_data)
        else:
            other_char = second_character if first_character.id == PLAYER_ID else first_character
            if other_char:
                renpy.exports.show(' '.join([other_char.title, 'full']))
            renpy.exports.say(None, plan.get_beginning_text(
                ReplacementText(first_character, second_character, first_character.place)
            ))
            if other_char:
                renpy.exports.hide(' '.join([other_char.title, 'full']))

    if DEBUG_SIMULATION:
        logger.info('new plan {}{} for {}'.format(
            plan.title, '({})'.format(second_character.title) if second_character else '', first_character.title
        ))


def set_plan_single(stage, current_seconds, current_day_seconds, first_character):
    filters = stage.filters_plan_set
    first_filters = filters.first_character
    if get_and_set_plan(current_seconds, current_day_seconds, first_character, plan_filters=first_filters):
        return True
    if not stage.effects_id:
        plan_data = first_character.plan_data
        if stage.is_optional:
            if not plan_data.next_stage():
                plan_data.finish_plan(current_seconds)
        else:
            if DEBUG_SIMULATION:
                logger.info('plan filters not passed')
            plan_data.finish_plan(current_seconds, is_interrupted=True)
        return True
    return False


def set_plan_group(stage, current_seconds, current_day_seconds, first_character, second_character):
    filters = stage.filters_plan_set
    first_filters = filters.first_character
    second_filters = filters.second_character
    if first_filters is not None and second_filters is not None:
        raise ValueError('Only one plan filters allowed for plan item')
    elif first_filters is not None:
        is_set = get_and_set_plan(
            current_seconds, current_day_seconds, first_character, second_character, plan_filters=first_filters
        )
    elif second_filters is not None:
        is_set = get_and_set_plan(
            current_seconds, current_day_seconds, second_character, first_character, plan_filters=second_filters
        )
    else:
        raise ValueError('Group set plan filters not found')
    if is_set:
        return True
    elif not stage.effects_id:
        plan_data = first_character.plan_data
        if stage.is_optional:
            if not plan_data.next_stage():
                plan_data.finish_plan(current_seconds)
        else:
            plan_data.finish_plan(current_seconds, is_interrupted=True)
        return True
    return False
