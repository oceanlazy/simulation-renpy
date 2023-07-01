from __future__ import division

import datetime
import json
import os
import kernel.models as models

from kernel import BASE_DIR

db = {}
classes = {}

db_path = os.path.join(BASE_DIR, 'kernel', 'db')
for path_ in os.listdir(db_path):
    if path_ == '.empty':
        continue
    if not os.path.isfile(os.path.join(db_path, path_)):
        continue
    with open(os.path.join(db_path, path_)) as f_:
        data = json.load(f_)

    model_name = data['name']
    for k in list(data['objects']):
        row = data['objects'][k]
        for row_k in row.keys():
            if row_k not in data['time_fields']:
                continue
            row_v = row[row_k]
            if not row_v:
                continue
            row[row_k] = datetime.time(hour=int(row_v[:2]), minute=int(row_v[3:5]), second=int(row_v[6:8]))
        if not isinstance(k, int) and k.isdigit():
            data['objects'][int(k)] = data['objects'].pop(k)

    db[model_name] = data
    klass = getattr(models, model_name, None)
    if klass:
        classes[model_name] = klass

for model_name, klass in classes.items():
    class_data = db[model_name]

    klass.db_data = class_data
    klass.db_objects = class_data['objects']
    klass.defaults = class_data['defaults']
    klass.mtm_data = class_data['mtm_data'] or {}
    klass.mto_data = class_data['mto_data'] or {}
    klass.set_data = class_data['set_data'] or {}
    klass.db_attrs_range = class_data['attrs_ranges']
    klass.objects = klass.get_new_queryset()
    klass.objects_fields = set(class_data['objects_fields'])
    klass.objects_effects_fields = set(class_data['objects_effects_fields'])

    for mtm_data in klass.mtm_data.values():
        mtm_data['model'] = classes[mtm_data['model']]
        mtm_data['through'] = db[mtm_data['through']]

    for mto_data in klass.mto_data.values():
        mto_data['model'] = classes[mto_data['model']]

    for set_data in klass.set_data.values():
        set_data['model'] = classes[set_data['model']]
