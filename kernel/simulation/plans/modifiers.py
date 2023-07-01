from __future__ import division


class PlanModifiers(object):
    value_min = 100
    value_max = 1000

    def __init__(self, instance, points_mods):
        self.instance = instance
        self.points_mods = points_mods

    def get(self):
        values = []
        for attrs_type_key in self.points_mods:
            attrs_type_values = self.points_mods[attrs_type_key]
            values.append(self.get_modified_effect(self.instance, attrs_type_key, attrs_type_values) * 10)
        return sum(values) / (len(values) * 10)

    def get_mod(self, value=None):
        mod = self.get() / 500
        if value and mod != 1:
            mod_value = (mod - 1) * value + 1
            if mod_value < 0.1:
                return 0.1
            return round(mod_value, 4)
        return mod

    def get_modified_effect(self, instance, attr_key, attr_value):
        if attr_key == 'exact':
            value = getattr(instance, attr_value)
        else:
            attrs = [getattr(instance, name) for name in attr_value]
            if attr_key == 'max':
                value = max(attrs)
            elif attr_key == 'min':
                value = min(attrs)
            elif attr_key == 'avg':
                value = sum(attrs) / len(attrs)
            else:
                raise ValueError('Value not found')
        if value > self.value_max:
            value = self.value_max
        elif value < self.value_min:
            value = self.value_min
        return value


class PlanModifiersPosNeg(PlanModifiers):
    def get(self):
        values = []
        for pos_neg_key in self.points_mods:
            pos_neg_values = self.points_mods[pos_neg_key]
            for attrs_type_key in pos_neg_values:
                attrs_type_values = pos_neg_values[attrs_type_key]
                values.append(
                    self.get_modified_effect(pos_neg_key, self.instance, attrs_type_key, attrs_type_values) * 10
                )
        return sum(values) / (len(values) * 10)

    def get_modified_effect(self, pos_neg_key, *args):
        value = super(PlanModifiersPosNeg, self).get_modified_effect(*args)
        if pos_neg_key == 'negative':
            value = self.value_max - value
        return value


class CharacterPlanModifiers(PlanModifiersPosNeg):
    def __init__(self, instance, points_mods, char_other=None, is_relationships_own=None, is_relationships_other=None):
        super().__init__(instance, points_mods)
        self.char_other = char_other
        self.is_relationships_own = is_relationships_own
        self.is_relationships_other = is_relationships_other

    def get(self):
        char_own = self.instance
        char_other = self.char_other

        if char_other is not None:
            relationship_own = char_own.get_opinion(char_other.id) if self.is_relationships_own else None
            relationship_other = char_other.get_opinion(char_own.id) if self.is_relationships_other else None
        else:
            relationship_own = None
            relationship_other = None

        values = []
        for pos_neg_key in self.points_mods:
            pos_neg_values = self.points_mods[pos_neg_key]
            for own_other_key in pos_neg_values:
                own_other_values = pos_neg_values[own_other_key]
                if own_other_key == 'own':
                    char = char_own
                    char.relationship = relationship_own
                else:
                    char = char_other
                    char.relationship = relationship_other
                for attrs_action_key in own_other_values:
                    attrs = own_other_values[attrs_action_key]
                    values.append(self.get_modified_effect(pos_neg_key, char, attrs_action_key, attrs) * 10)
                del char.relationship

        return sum(values) / (len(values) * 10)
