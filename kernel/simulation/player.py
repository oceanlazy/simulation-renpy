from kernel.models import Place, Plan
from kernel.simulation.plans.apply import set_plan
from kernel.simulation.plans.create import GetPlan
from kernel.simulation.routes.create import create_route_targeted
from kernel.utils import player_data
from kernel import renpy


class PlayerController(object):
    def __init__(self, player, simulation):
        self.player = player
        self.simulation = simulation
        self.plan_travelling = Plan.objects.get(title='player_travelling_game')
        self.plan_waiting = Plan.objects.get(title='player_waiting_game')

    def get_plan(self):
        return GetPlan(
            current_seconds=self.simulation.time.seconds,
            current_day_seconds=self.simulation.time.get_day_seconds(),
            char=self.player,
            filters={'is_player_available': True}
        ).get_plan()

    def choose_action_init(self):
        if player_data['is_plans_not_found']:
            plan, second_character = self.get_plan()
            if plan:
                player_data['is_plans_not_found'] = False

    def move_to_choose(self):
        places_ids = self.player.place.from_place_set.filter().values_list('to_place_id')
        places = Place.objects.filter(id__in=places_ids).order_by('-place_type')
        places = [place.name if place.is_lock(self.player) else place for place in places]
        to_place = renpy.store.generate_menu(places, 'name')
        if to_place == 'cancel':
            return
        with renpy.store.SayScreenHide():
            self.move_to(to_place.id)

    def move_to(self, to_place_id):
        plan_data = self.player.plan_data
        if not plan_data:
            set_plan(self.plan_travelling, self.player, self.simulation.time.seconds, is_interaction=False)
            plan_data = self.player.plan_data
        route, status = create_route_targeted(to_place_id, plan_data.first_character, plan_data.second_character)
        if status != 'in_progress':
            renpy.exports.say(None, 'Path not found.')
            return
        plan_data.update(first_route=route)
        self.simulation.simulate()

    def choose_plan(self):
        player_data['is_choose_plan'] = True
        plan, second_character = self.get_plan()
        if plan:
            with renpy.store.SayScreenHide():
                set_plan(plan, self.player, self.simulation.time.seconds, second_character)
                self.simulation.simulate()
        elif player_data['is_plans_not_found']:
            with renpy.store.SayScreenHide():
                renpy.exports.say(None, 'Actions not found.')
        player_data['is_choose_plan'] = False

    def next_stage(self):
        player_data['suitable_places'] = []
        self.player.plan_data.next_or_finish(self.simulation.time.seconds)
        with renpy.store.SayScreenHide():
            self.simulation.simulate()

    def cancel_plan(self):
        player_data['suitable_places'] = []
        self.player.plan_data.finish_plan(self.simulation.time.seconds)

    def wait(self):
        with renpy.store.SayScreenHide():
            set_plan(self.plan_waiting, self.player, self.simulation.time.seconds, is_interaction=False)
            self.simulation.simulate(minutes=15)
        plan_data = self.player.plan_data
        if plan_data and plan_data.plan is self.plan_waiting:
            plan_data.finish_plan(self.simulation.time.seconds)
