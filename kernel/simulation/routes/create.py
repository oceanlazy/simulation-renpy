import itertools
import logging
import random

from kernel.settings import DEBUG_SIMULATION, PLAYER_ID
from kernel.models import Place, Route
from kernel.simulation.routes.search import RouteSearch
from kernel.utils import get_filters_replaced, route_locked_places, player_data

logger = logging.getLogger('simulation')


class RouteCreate(object):
    def __init__(self, filters_data, first_character, second_character=None):
        self.status = None
        self.filters_data = filters_data
        self.first_character = first_character
        self.first_character_id = first_character.id
        self.first_character_update_data = {}
        self.second_character = second_character
        self.second_character_id = second_character.id if second_character else None
        self.second_character_update_data = {}
        self.plan_data_update_data = {}

    def create_route(self):
        data = {self.first_character_id: (None, None), self.second_character_id: (None, None)}
        to_place_id = None
        char_other = self.second_character

        for char in itertools.cycle([self.first_character, self.second_character]):
            if char is None or data[char.id][1] == 'finished':
                continue
            if char_other:
                route_other, status_other = data[char_other.id]
            else:
                route_other, status_other = None, None
            if status_other == 'finished':
                to_place_id = route_other.get_last_place_id()
            if to_place_id:
                route, status = create_route_targeted(to_place_id, char, char_other, self.filters_data.max_distance)
            else:
                route, status = create_route(self.filters_data, char, char_other)
            if status == 'not_found':
                self.status = status
                return
            data[char.id] = (route, status)
            if not char_other or char.place_id == char_other.place_id:
                self.status = status
                break
            last_place = route.get_last_place() if route else char.place
            if route_other and last_place is route_other.get_last_place():
                self.status = 'in_progress'
                break
            to_place_id = last_place.id
            char_other = char

        for data, key in (
            (data[self.first_character_id], 'first_route'), (data[self.second_character_id], 'second_route')
        ):
            route, route_status = data
            if route:
                self.plan_data_update_data[key] = route

        if self.first_character_id == PLAYER_ID and self.status == 'in_progress' and not player_data['suitable_places']:
            player_data['is_break_simulation'] = True
            first_route = self.plan_data_update_data.get('first_route')
            second_route = self.plan_data_update_data.get('second_route')
            if first_route and second_route and first_route is not second_route:
                player_data['suitable_places'] = [first_route.places[first_route.route_distance]]
            else:
                player_data['suitable_places'] = first_route.suitable_places

    def teleportation(self):
        qs_filters = get_filters_replaced(self.filters_data.filters, self.first_character, self.second_character)
        places = Place.objects.filter(**qs_filters).instances
        if not places:
            if DEBUG_SIMULATION:
                logger.info('not found place for teleportation')
            self.status = 'not_found'
            return

        is_random = self.filters_data.is_random
        attrs_importance = self.filters_data.attrs_importance
        place_points = {}
        for p in places:
            place_points[get_place_points(p, attrs_importance, is_random)] = p
        if not place_points:
            if DEBUG_SIMULATION:
                logger.info('not found place for teleportation')
            self.status = 'not_found'
            return
        place = place_points[max(place_points)]

        for char in (self.first_character, self.second_character):
            if char is None:
                continue
            if char.id == self.first_character_id:
                self.first_character_update_data['place'] = place
            else:
                self.second_character_update_data['place'] = place
        self.status = 'finished'

    def run(self):
        if self.filters_data.is_teleportation:
            self.teleportation()
        else:
            self.create_route()

    def apply(self):
        if self.plan_data_update_data:
            self.first_character.plan_data.update(**self.plan_data_update_data)
        if self.first_character_update_data:
            self.first_character.update(**self.first_character_update_data)
        if self.second_character_update_data:
            self.second_character.update(**self.second_character_update_data)


def get_place_points(place, attrs_importance=None, is_random=False):
    if attrs_importance:
        points = sum(
            (random.randint(100, 1000) if k == 'random' else getattr(place, k)) * v
            for k, v in attrs_importance.items()
        )
    else:
        points = random.randint(100, 1000) if is_random else 500
    return points


def create_route(filters_data, first_character, second_character=None, from_place=None):
    qs_filters = get_filters_replaced(filters_data.filters, first_character, second_character)
    places = Place.objects.filter(**qs_filters).instances
    from_place = from_place if from_place is not None else first_character.place
    from_place_id = from_place.id

    if not places:
        return None, 'not_found'
    if first_character.is_chained or from_place.is_lock(first_character):
        if first_character.place in places:
            return None, 'finished'
        route_locked_places[first_character.id].add(first_character.place_id)
        return None, 'not_found'

    is_random = filters_data.is_random
    is_nearest = 0
    attrs_importance = filters_data.attrs_importance
    distance_penalty = filters_data.distance_penalty
    max_distance = filters_data.max_distance or 9999
    locked_places = route_locked_places[first_character.id]
    place_routes_points = {}
    nearest_transitions = None

    for p in places:
        search = RouteSearch(from_place_id, p.id, exclude=locked_places, max_distance=max_distance)
        search.run()
        if search.transitions is None:
            continue
        if is_nearest:
            if search.distance < max_distance:
                max_distance = search.distance
                nearest_transitions = search.transitions
            continue
        points = get_place_points(p, attrs_importance, is_random)
        if distance_penalty:
            points -= distance_penalty * search.distance
        place_routes_points[points] = search.transitions

    if is_nearest:
        transitions = nearest_transitions
    else:
        transitions = place_routes_points[max(place_routes_points)] if place_routes_points else None

    if transitions is None:
        return None, 'not_found'
    if not transitions:  # already in place
        return None, 'finished'
    if not second_character or second_character.place_id != first_character.place_id:
        second_character = None
    route = Route.create(
        transitions=transitions,
        first_character=first_character,
        second_character=second_character,
        start_place_id=from_place_id
    )
    route.suitable_places = []
    if first_character.id == PLAYER_ID:
        if is_nearest:
            route.suitable_places = [nearest_transitions[-1].to_place]
        else:
            route.suitable_places = [ts[-1].to_place if ts else first_character.place for ts in sorted(
                place_routes_points.values(), key=lambda ts: sum([pt.distance for pt in ts]) if ts else 0
            )]
    return route, 'in_progress'


def create_route_targeted(to_place_id, first_character, second_character=None, max_distance=None):
    locked_places = route_locked_places[first_character.id]
    from_place = first_character.place
    from_place_id = from_place.id
    if from_place_id == to_place_id:
        return None, 'finished'
    if first_character.is_chained or from_place.is_lock(first_character):
        locked_places.add(from_place_id)
        return None, 'not_found'
    search = RouteSearch(
        from_place_id=from_place_id,
        to_place_id=to_place_id,
        exclude=locked_places,
        max_distance=max_distance
    )
    search.run()

    if not search.transitions:
        return None, 'not_found'
    if not second_character or second_character.place_id != first_character.place_id:
        second_character = None

    route = Route.create(
        transitions=search.transitions,
        first_character=first_character,
        second_character=second_character,
        start_place=from_place,
        is_targeted=True
    )
    route.suitable_places = [search.transitions[-1].to_place] if first_character.id == PLAYER_ID else []
    return route, 'in_progress'


def create_route_plan(stage, plan_data, current_seconds, first_character, second_character=None):
    route_create = RouteCreate(stage.filters_place, first_character, second_character)
    route_create.run()
    route_create.apply()
    if route_create.status != 'in_progress':
        if route_create.status == 'finished':
            if DEBUG_SIMULATION and not stage.filters_place.is_teleportation:
                logger.info('already in place')
            if not plan_data.next_stage():
                plan_data.finish_plan(current_seconds)
            return False
        if DEBUG_SIMULATION:
            logger.info('route {}'.format(route_create.status))
        if stage.is_optional:
            if not plan_data.next_stage():
                plan_data.finish_plan(current_seconds, is_interrupted=True)
        else:
            plan_data.finish_plan(current_seconds, is_interrupted=True)
        return False
    return True
