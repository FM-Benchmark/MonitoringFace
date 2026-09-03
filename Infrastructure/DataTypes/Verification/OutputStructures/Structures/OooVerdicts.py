from typing import Dict, List, Optional, Tuple

from Infrastructure.DataTypes.Verification.OutputStructures.AbstractOutputStrucutre import AbstractOutputStructure
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.Assignment import Assignment
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.Proposition import Proposition
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.ValueType import ValueType
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.VariableOrder import VariableOrdering


class OooVerdicts(AbstractOutputStructure):
    def __init__(self, variable_order: VariableOrdering):
        # tp -> [(arrival_idx, time_stamp, values), ...] in arrival order
        self.by_tp: Dict[int, List[Tuple[int, Optional[int], List[ValueType]]]] = dict()
        self.tp_to_ts = dict()
        self.variable_order = variable_order
        self.out_of_order_inserts = 0
        self._arrival_counter = 0
        self._max_tp_seen: Optional[int] = None

    def retrieve_order(self):
        return self.variable_order.retrieve_order()

    def time_points(self) -> Dict[int, int]:
        return self.tp_to_ts

    def as_oracle(self, other: 'AbstractOutputStructure') -> Tuple[bool, str]:
        from Infrastructure.DataTypes.Verification.OutputStructures.Compare.OooVerdictsComparator import as_oracle
        return as_oracle(self, other)

    def retrieve(self, time_point):
        if time_point not in self.tp_to_ts:
            return None
        selected = [x for (_, _, vals) in self.by_tp.get(time_point, []) for x in vals]
        return self.tp_to_ts[time_point], time_point, selected

    def insert(self, value, time_point, time_stamp):
        self.tp_to_ts[time_point] = time_stamp
        values = value if isinstance(value, list) else [value]
        if self.variable_order:
            values = list(map(lambda va: Assignment(va, self.variable_order), values))
        else:
            values = list(map(lambda va: Proposition(va), values))
        if self._max_tp_seen is not None and time_point < self._max_tp_seen:
            self.out_of_order_inserts += 1
        else:
            self._max_tp_seen = time_point
        self.by_tp.setdefault(time_point, []).append((self._arrival_counter, time_stamp, values))
        self._arrival_counter += 1

    def entry_count(self) -> int:
        return self._arrival_counter

    def in_arrival_order(self) -> List[Tuple[Optional[int], int, List[ValueType]]]:
        entries = [(idx, ts, tp, vals) for tp, chunks in self.by_tp.items() for (idx, ts, vals) in chunks]
        entries.sort(key=lambda entry: entry[0])
        return [(ts, tp, vals) for (_, ts, tp, vals) in entries]
