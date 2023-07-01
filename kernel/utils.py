from __future__ import division

import ctypes
import logging
import time
import sys

from collections import defaultdict

group_times = defaultdict(int)
plan_pauses = defaultdict(lambda: defaultdict(int))
stay_until_seconds = defaultdict(int)
route_locked_places = defaultdict(set)
qs_cache = defaultdict(dict)
qs_cache_relations = defaultdict(list)
qs_cache_search_groups = defaultdict(tuple)
qs_stat = defaultdict(list)
called_qs_cache = defaultdict(int)
called_caches_types = defaultdict(int)
called_qs = defaultdict(int)
player_data = defaultdict(list)
relations_cache = {}


logger_simulation = logging.getLogger('simulation')
if sys.version_info[0] >= 3:
    unicode = str
else:
    unicode = unicode  # noqa


class ReplacementText(object):
    def __init__(self, first_character, second_character, place):
        self.first_character = first_character
        self.second_character = second_character
        self.place = place


class Mock(object):
    def __init__(self, names_values=None, return_value=None):
        self.names_values = names_values or {}
        self.return_value = return_value or {}

    def __bool__(self):
        return False

    def __getattr__(self, item):
        return Mock(self.names_values, return_value=self.names_values.get(item))

    def __call__(self, *args, **kwargs):
        if self.return_value is not None:
            return self.return_value
        return Mock(self.names_values)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return


# time
class FILETIME(ctypes.Structure):
    _fields_ = [('dwLowDateTime', ctypes.c_uint), ('dwHighDateTime', ctypes.c_uint)]


def time_ctypes():
    """Accurate version of time.time() for windows, return UTC time in seconds since 01/01/1601"""
    file_time = FILETIME()
    ctypes.windll.kernel32.GetSystemTimePreciseAsFileTime(ctypes.byref(file_time))
    return (file_time.dwLowDateTime + (file_time.dwHighDateTime << 32)) / 1.0e7


def time_linux():
    return round(time.time() * 1000, 2)


def combine_data(*args):
    data = defaultdict(int)
    for d in args:
        for k in d:
            v = d[k]
            if isinstance(v, (int, float)):
                data[k] += v
            else:
                data[k] = v
    return data


def get_related_value(instance, name):
    if '__' in name:
        relations = name.split('__')
        name = relations.pop()
        for related_name in relations:
            instance = getattr(instance, related_name)
    return getattr(instance, name)


def get_value_replaced(instance, name):
    if name.startswith('_'):
        return get_related_value(instance, name[1:])
    return name


def get_value_replaced_second_char(name, first, second=None):
    if name.startswith('_'):
        if name.startswith('_second_char'):
            return get_related_value(second, name[13:])
        return get_related_value(first, name[1:])
    return name


def get_filters_replaced(filters, char, second_char=None):
    filters_new = {}
    for filter_k, filter_v in filters.items():
        if isinstance(filter_v, int) or filter_v is None:
            filters_new[filter_k] = filter_v
        elif isinstance(filter_v, (str, unicode)):
            filters_new[filter_k] = get_value_replaced_second_char(filter_v, char, second_char)
        elif isinstance(filter_v, list):
            filters_new[filter_k] = [
                get_value_replaced_second_char(v, char, second_char)
                if isinstance(v, (str, unicode)) else v for v in filter_v
            ]
        else:
            filters_new[filter_k] = filter_v
    return filters_new


def is_in_time_range(current_seconds, stage_filters):
    from_seconds = stage_filters.time_from_seconds
    to_seconds = stage_filters.time_to_seconds
    if from_seconds and to_seconds:
        if from_seconds <= to_seconds:
            return from_seconds <= current_seconds <= to_seconds
        return current_seconds >= from_seconds or current_seconds <= to_seconds
    elif from_seconds:
        return current_seconds >= from_seconds
    elif to_seconds:
        return current_seconds <= to_seconds
    return True


def dict_multiply(data, time_passed):
    if time_passed == 1:
        return dict(data)
    return {k: v * 1000 * time_passed / 1000 for k, v in data.items()}
