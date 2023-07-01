from __future__ import print_function

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import time
from io import StringIO

from kernel.models import Character, Plan, PlanData
from kernel.settings import PLAYER_ID
from kernel.simulation.sim import Simulation
from kernel import profiler


def timer(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        func(*args, **kwargs)
        print("Tests took {} seconds to complete".format(round(time.time() - start, 2)))
        sio = StringIO()
        profiler.print_stats(sio, output_unit=1e-03)
        print(sio.getvalue())
    return wrapper


@timer
def test_simulation():
    simulation.simulate(seconds=22, minutes=720)


@timer
def test_simulation_player_plan():
    first_character = player
    plan = Plan.objects.get(title='working')
    plan_data = PlanData.create(plan=plan, first_character=first_character)
    first_character.update(plan_data=plan_data)
    simulation.simulate()


@timer
def test_simulation_player_plan_group():
    first_character = player
    second_character = Character.objects.get(title='merlin')
    plan = Plan.objects.get(title='small_talk')
    plan_data = PlanData.create(plan=plan, first_character=first_character, second_character=second_character)
    first_character.update(plan_data=plan_data)
    second_character.update(plan_data=plan_data)
    simulation.simulate()


if __name__ == '__main__':
    player = Character(PLAYER_ID)
    simulation = Simulation()
    test_simulation()
