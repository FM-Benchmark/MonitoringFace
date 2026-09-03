from typing import List, Any, Tuple, AnyStr

from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.ValueType import ValueType
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.VariableOrder import VariableOrdering


class Assignment(ValueType):
    def __init__(self, values: List[Any], variable_order: VariableOrdering):
        self.order = variable_order.retrieve_order()
        self.values = values
        self._canonical = tuple(sorted(zip(self.order, self.values)))

    def __repr__(self):
        return f"Assignment({self.values}, {self.order})"

    def __eq__(self, other):
        if not isinstance(other, Assignment):
            return False
        return self._canonical == other._canonical

    def __hash__(self) -> int:
        return hash(self._canonical)

    def __lt__(self, other):
        if not isinstance(other, Assignment):
            return NotImplemented
        return self._canonical < other._canonical

    def __le__(self, other):
        if not isinstance(other, Assignment):
            return NotImplemented
        return self._canonical <= other._canonical

    def __gt__(self, other):
        if not isinstance(other, Assignment):
            return NotImplemented
        return self._canonical > other._canonical

    def __ge__(self, other):
        if not isinstance(other, Assignment):
            return NotImplemented
        return self._canonical >= other._canonical

    def to_representation(self) -> List[Tuple[Any, AnyStr]]:
        return list(zip(self.values, self.order))

    def retrieve_order(self, new_order: VariableOrdering) -> 'Assignment':
        if self.order == new_order.retrieve_order():
            return self
        mapping = {v: val for v, val in zip(self.values, self.order)}
        if set(self.values) != set(new_order.retrieve_order()):
            raise ValueError("New order must contain exactly the same variable names.")
        return Assignment([mapping[v] for v in new_order.retrieve_order()], new_order)

    def retrieve_value(self, key):
        return self.values[self.order.index(key)]
