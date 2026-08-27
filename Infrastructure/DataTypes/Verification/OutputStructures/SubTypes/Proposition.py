from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.ValueType import ValueType


class Proposition(ValueType):
    def __init__(self, value: bool):
        self.value = value

    def __eq__(self, other):
        return self.value == other.value
