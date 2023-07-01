import logging

from kernel.settings import DEBUG_ROUTE_SEARCH
from kernel.models import Place, PlaceTransition


logger = logging.getLogger('route')


class RouteSearch:
    distance = None
    transitions = None
    transitions_distances = None

    def __init__(self, from_place_id, to_place_id, safety_min=100, beauty_min=100, exclude=None, max_distance=9999):
        self.from_place_id = from_place_id
        self.to_place_id = to_place_id
        self.transitions = []
        self.transitions_distances = []
        self.safety_min = safety_min
        self.beauty_min = beauty_min
        self.max_distance = max_distance or 9999
        self.exclude_places = exclude or {}
        self.base_filters = {}
        if self.safety_min > 100:
            self.base_filters['to_place__safety__gte'] = safety_min
        if self.beauty_min > 100:
            self.base_filters['to_place__beauty__gte'] = beauty_min

    def __str__(self):
        return '{} > {}'.format(Place(self.from_place_id).title, Place(self.to_place_id).title)

    def build_routes(self, from_place_id, prev_transition=None, transitions=None, to_places=None):
        transitions = list(transitions or [])
        to_places = to_places or set()

        qs_filters = {'from_place_id': from_place_id}
        to_place_id = prev_transition.from_place_id if prev_transition is not None else self.to_place_id
        qs_filters['to_place_id'] = to_place_id
        transition = PlaceTransition.objects.get(**qs_filters)
        if transition:
            transitions.append(transition)
            route_distance = self.get_route_distance(transitions)
            if (
                (not self.transitions_distances or route_distance < min(self.transitions_distances)) and
                route_distance <= self.max_distance and
                to_place_id not in self.exclude_places
            ):
                self.transitions.append(transitions)
                self.transitions_distances.append(route_distance)
                if DEBUG_ROUTE_SEARCH:
                    logger.info('{} {} {}'.format('+' * 40, route_distance, transition))
            return

        qs_filters = dict(self.base_filters)
        qs_filters['to_place_id'] = to_place_id
        if prev_transition:
            qs_filters['from_place_id__ne'] = prev_transition.to_place_id

        count = 0
        for count, transition in enumerate(PlaceTransition.objects.filter(**qs_filters)):
            if transition.from_place_id in to_places:
                if DEBUG_ROUTE_SEARCH:
                    logger.info('{} in to_places'.format(transition.from_place_id))
                return
            if count:
                transitions[-1] = transition
            else:
                transitions.append(transition)
            route_distance = self.get_route_distance(transitions)
            if route_distance > self.max_distance:
                if DEBUG_ROUTE_SEARCH:
                    logger.info('distance limit: {} > {}'.format(route_distance, self.max_distance))
                continue
            if transition.to_place_id in self.exclude_places:
                if DEBUG_ROUTE_SEARCH:
                    logger.info('excluded place: {}'.format(transition.to_place_id))
                continue
            if not self.transitions_distances or route_distance < min(self.transitions_distances):
                if DEBUG_ROUTE_SEARCH:
                    logger.info('route size: {} {}'.format(len(transitions) or 'zero', transition))
                to_places.add(to_place_id)
                self.build_routes(from_place_id, transition, transitions, to_places)
        if DEBUG_ROUTE_SEARCH:
            if not count:
                logger.info('transitions not found')
            logger.info('*' * 40)

    def run(self):
        if self.from_place_id == self.to_place_id:
            self.transitions = []
            self.distance = 0
            return
        if self.from_place_id in self.exclude_places or self.to_place_id in self.exclude_places:
            self.transitions = None
            self.distance = None
            return

        self.build_routes(self.from_place_id)
        if not self.transitions:
            self.transitions = None
            self.distance = None
            return
        self.distance = min(self.transitions_distances)
        self.transitions = self.transitions[self.transitions_distances.index(self.distance)][::-1]

    @staticmethod
    def get_route_distance(route):
        # https://docs.python.org/3/tutorial/floatingpoint.html
        return sum([r.distance*1000 for r in route]) / 1000
