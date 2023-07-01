import re

from builtins import object
from sys import platform
from kernel.settings import DEBUG_ORM
from kernel.utils import (
    called_caches_types, called_qs, called_qs_cache, qs_cache, qs_cache_relations, qs_cache_search_groups, qs_stat
)

if platform == 'linux2':
    from kernel.utils import time_linux as time_ns
else:
    from kernel.utils import time_ctypes as time_ns


LOOKUP_COMMANDS = {'exact', 'ne', 'gte', 'gt', 'lte', 'lt', 'in', 'nin', 'isnull'}


class SearchRelations(object):
    relation = ''
    relations_index = 0

    def __init__(self, relations, initial_pk, model, field_name):
        self.relations = relations
        self.field_name = field_name

        self.num_relations = len(relations)
        self.model_data = model.db_data
        self.from_pks = [initial_pk]

    def search(self):
        self.relation = self.relations[self.relations_index]
        self.relations_index += 1
        if self.relation in self.model_data['mto_data']:
            self.process_mto_relation()
        elif self.relation in self.model_data['mtm_data']:
            self.process_mtm_relation()
        elif self.relation.endswith('_set'):
            self.process_set_relation()
        else:
            raise ValueError('Relation not found')

        if self.num_relations == self.relations_index:
            return [row for row in self.model_data['objects'].values() if row['id'] in self.from_pks]
        return self.search()

    def process_mto_relation(self):
        relation_data = self.model_data['mto_data'][self.relation]
        from_id_key = relation_data['from_id']
        objects = self.model_data['objects']
        new_from_pks = [row[from_id_key] for row in objects.values() if row['id'] in self.from_pks]
        new_model_data = relation_data['model'].db_data

        self.from_pks = new_from_pks
        self.model_data = new_model_data

    def process_mtm_relation(self):
        relation_data = self.model_data['mtm_data'][self.relation]
        from_id_key = relation_data['from_id']
        target_id_key = relation_data['target_id']
        through_data = relation_data['through']
        objects = through_data['objects']

        if (
                self.num_relations == self.relations_index and
                self.field_name != 'id' and
                self.field_name in through_data['objects_fields']
        ):
            new_from_pks = [k['id'] for k in objects.values() if k[from_id_key] in self.from_pks]
            new_model_data = through_data
        else:
            new_from_pks = [k[target_id_key] for k in objects.values() if k[from_id_key] in self.from_pks]
            new_model_data = relation_data['model'].db_data

        self.from_pks = new_from_pks
        self.model_data = new_model_data

    def process_set_relation(self):
        relation_data = self.model_data['set_data'][self.relation]
        target_id_key = relation_data['target_id']
        new_model_data = relation_data['model'].db_data
        objects = new_model_data['objects']
        new_from_pks = [k['id'] for k in objects.values() if k[target_id_key] in self.from_pks]

        self.from_pks = new_from_pks
        self.model_data = new_model_data


class QuerySet(object):
    base_filters = None
    base_filters_exclude = None
    model = None
    instances = None

    def __contains__(self, item):
        return item in self.instances

    def __getitem__(self, item):
        return self.instances[item]

    def __init__(self, model, base_filters=None, base_filters_exclude=None):
        self.instances = []
        self.model = model
        if base_filters:
            self.base_filters = base_filters
        if base_filters_exclude:
            self.base_filters_exclude = base_filters_exclude

    def __bool__(self):
        return bool(self.instances)

    def __str__(self):
        return 'QuerySet({})'.format(', '.join(map(str, self.instances)))

    def __repr__(self):
        return 'QuerySet({})'.format(self.instances)

    def __len__(self):
        return len(self.instances)

    @staticmethod
    def check_command_condition(cmd, first, second):
        if cmd in 'exact':
            return first == second
        if cmd == 'gte':
            return first >= second
        if cmd == 'gt':
            return first > second
        if cmd == 'isnull':
            return (first is None) == second
        if cmd in 'ne':
            return first != second
        if cmd == 'lte':
            return first <= second
        if cmd == 'in':
            return first in second
        if cmd == 'lt':
            return first < second
        if cmd == 'nin':
            return first not in second

        raise ValueError('Cmd: "{}" not found'.format(cmd))

    def count(self, check_for_deleted=False):
        if check_for_deleted:
            return len([obj for obj in self.instances if obj.id])
        else:
            return len(self.instances)

    def exclude(self, **kwargs):
        qs = self.get_new_qs()
        if not any(kwargs.values()):
            qs.instances = self.instances
            return qs
        if qs.base_filters_exclude:
            qs.base_filters_exclude.update(kwargs)
        else:
            qs.base_filters_exclude = kwargs
        qs.instances = self._exclude_results(self.instances, qs.base_filters_exclude)
        return qs

    def _exclude_results(self, results, kwargs):
        filters_number = len(kwargs)
        if not filters_number:
            return results
        ids_to_remove = []
        for instance in results:
            filters_passed = 0
            for filter_name, filter_value in kwargs.items():
                relations, lookup, cmd = self.parse_filter(filter_name)
                attr_value = getattr(instance, lookup, None)
                if attr_value and self.check_command_condition(cmd, attr_value, filter_value):
                    filters_passed = 1
            if filters_number == filters_passed:
                ids_to_remove.append(instance.id)  # .remove distorts the iteration
        return [i for i in results if i.id not in ids_to_remove]

    def get_new_qs(self):
        return QuerySet(self.model, dict(self.base_filters or {}), dict(self.base_filters_exclude or {}))

    @staticmethod
    def parse_filter(lookup):
        lookup_relations = lookup.split('__')
        cmds = LOOKUP_COMMANDS & set(lookup_relations)
        if cmds:
            cmd = cmds.pop()
            lookup_relations.remove(cmd)
        else:
            cmd = 'exact'
        field_name = lookup_relations.pop()
        return lookup_relations, field_name, cmd

    def parse_search_lookups(self, lookups):
        """:rtype: tuple"""
        base_group = {'total': 0, 'passed': 0, 'failed': 0}
        groups = {}
        filters_data = {}

        for lookup in lookups:
            if '__or' in lookup:
                regex = re.search(r'__or([0-9])?(a)?([0-9])?$', lookup)
                if regex:
                    lookup_no_or, _ = lookup.rsplit('__', 1)
                    parse_data = self.parse_filter(lookup_no_or)
                else:
                    parse_data = self.parse_filter(lookup)
            else:
                regex = None
                parse_data = self.parse_filter(lookup)
            if not regex:
                base_group['total'] += 1
                filters_data[lookup] = {'parse_data': parse_data, 'group_or': None, 'group_and': base_group}
                continue

            group_num = regex.group(1) or '1'
            if regex.group(2):
                group_num_and = regex.group(3) or '1'
            else:
                group_num_and = None

            group_and = None
            if group_num in groups:
                group = groups[group_num]
                if group_num_and:
                    groups_and = group['groups_and']
                    group_and = groups_and.get(group_num_and)
                    if group_and:
                        group_and['total'] += 1
                    else:
                        group_and = {'total': 1, 'passed': 0, 'failed': 0}
                        groups_and[group_num_and] = group_and
                        group['total'] += 1
                else:
                    group['total'] += 1
            else:
                base_group['total'] += 1
                group = {'total': 1, 'passed': 0, 'failed': 0, 'groups_and': {}}
                if group_num_and:
                    group_and = {'total': 1, 'passed': 0, 'failed': 0}
                    group['groups_and'][group_num_and] = group_and
                groups[group_num] = group

            filters_data[lookup] = {'parse_data': parse_data, 'group_or': group, 'group_and': group_and}

        return base_group, groups, filters_data

    def filter(self, is_first_only=False, **kwargs):
        if DEBUG_ORM:
            qs_start = time_ns() * 1000000

        search_filters = dict(self.base_filters or {})
        search_filters.update(kwargs)

        model_name = self.model.__name__
        qs_cache_key = (model_name, str(search_filters), is_first_only)
        qs_cached = qs_cache.get(qs_cache_key)
        if qs_cached is not None:
            if DEBUG_ORM:
                called_qs_cache[qs_cache_key] += 1  # noqa
                called_caches_types[qs_cache_key] += 1
                qs_finish = time_ns() * 1000000 - qs_start  # noqa
                qs_stat[qs_cache_key].append(qs_finish)
            return qs_cached['queryset']

        qs = self.get_new_qs()
        qs.base_filters = search_filters
        db_objects = self.model.db_objects

        if search_filters:
            if 'id' in search_filters:
                pk = search_filters['id']
                db_objects = {pk: db_objects[pk]} if pk in db_objects else {}
            elif 'id__in' in search_filters:
                ids = search_filters.pop('id__in')
                db_objects = {pk: db_objects[pk] for pk in db_objects if pk in ids}
            elif 'id__nin' in search_filters:
                ids = search_filters.pop('id__nin')
                db_objects = {pk: db_objects[pk] for pk in db_objects if pk not in ids}

        groups_cached = qs_cache_search_groups[qs_cache_key]
        if groups_cached:
            base_group, groups, filters_data = groups_cached
        else:
            base_group, groups, filters_data = self.parse_search_lookups(search_filters)
            qs_cache_search_groups[qs_cache_key] = (base_group, groups, filters_data)

        results = []

        for pk in db_objects:
            if not search_filters:
                results.append(self.model(pk))
                if is_first_only:
                    break
                else:
                    continue

            row = db_objects[pk]

            base_group['failed'] = 0
            base_group['passed'] = 0
            for k in groups:
                group = groups[k]
                group['failed'] = 0
                group['passed'] = 0
                for group_and in group['groups_and'].values():
                    group_and['failed'] = 0
                    group_and['passed'] = 0
            is_passed = None

            for lookup in search_filters:
                if is_passed is not None:
                    break

                filter_v = search_filters[lookup]
                filter_data = filters_data[lookup]
                group_or = filter_data['group_or']
                group_and = filter_data['group_and']
                if group_or and group_or['passed']:
                    continue
                if group_and and group_and['failed']:
                    continue

                lookup_relations, field_name, cmd = filter_data['parse_data']
                if not field_name:
                    raise ValueError('Empty lookup')
                if lookup_relations:
                    relations_rows = SearchRelations(lookup_relations, row['id'], self.model, field_name).search()
                else:
                    relations_rows = [row]
                for relation_row in relations_rows:
                    if self.check_command_condition(cmd, relation_row[field_name], filter_v):
                        is_check_finish = True
                        if group_and:
                            group_and['passed'] += 1
                            if group_or:
                                if group_and['passed'] >= group_and['total']:
                                    group_or['passed'] += 1
                                    base_group['passed'] += 1
                                else:
                                    is_check_finish = False
                        else:
                            if group_or:
                                group_or['passed'] += 1
                            base_group['passed'] += 1
                        if is_check_finish and base_group['total'] == base_group['passed']:
                            is_passed = True
                        break
                else:
                    if group_or:
                        group_or['failed'] += 1
                        if group_or['total'] == group_or['failed']:
                            base_group['failed'] += 1
                            is_passed = False
                        if group_and:
                            group_and['failed'] = +1
                    else:
                        is_passed = False
                        break

            if is_passed:
                results.append(self.model(pk))
                if is_first_only:
                    break

        if qs.base_filters_exclude:
            results = self._exclude_results(results, qs.base_filters_exclude)
        qs.instances = results

        qs_relations = []
        for k in filters_data:
            lookup_relations = filters_data[k]['parse_data'][0]
            if lookup_relations:
                qs_relations.extend(lookup_relations)
        model = self.model
        qs_model_names = [model_name]
        model_mto_data = model.mto_data
        model_mtm_data = model.mtm_data
        model_set_data = model.set_data
        for relation in qs_relations:
            if relation in model_mto_data:
                qs_model_names.append(model_mto_data[relation]['model'].__name__)
            elif relation in model_mtm_data:
                data = model_mtm_data[relation]
                qs_model_names.extend((data['model'].__name__, data['through']['name']))
            elif relation in model_set_data:
                qs_model_names.append(model_set_data[relation]['model'].__name__)
        qs_cache[qs_cache_key] = {'queryset': qs, 'relations': qs_model_names}
        for qs_model_name in qs_model_names:
            qs_cache_relations[qs_model_name].append(qs_cache_key)

        if DEBUG_ORM:
            qs_finish = time_ns() * 1000000 - qs_start  # noqa
            qs_stat[qs_cache_key].append(qs_finish)
            called_qs[qs_cache_key] += 1

        return qs

    def get(self, **kwargs):
        try:
            return self.filter(is_first_only=True, **kwargs)[0]
        except IndexError:
            return None

    def first(self):
        if self.instances:
            return self.instances[0]

    def order_by(self, field):
        if field.startswith('-'):
            field = field.replace('-', '')
            is_reverse = True
        else:
            is_reverse = False
        qs = self.get_new_qs()
        qs.instances = sorted(self.instances, key=lambda instance: getattr(instance, field), reverse=is_reverse)
        return qs

    def values_list(self, attr_name):
        return [getattr(instance, attr_name) for instance in self.instances]

    def values_list_relations(self, lookup):
        relations, attr_name, cmd = self.parse_filter(lookup)
        if relations:
            values = []
            for instance in self.instances:
                relation_rows = SearchRelations(relations, instance.id, instance.__class__, attr_name).search()
                values.append(tuple(x[attr_name] for x in relation_rows))
            return values
        else:
            raise ValueError('Relations not found')

    def values(self, *args):
        return [tuple(getattr(i, arg) for arg in args) for i in self.instances]
