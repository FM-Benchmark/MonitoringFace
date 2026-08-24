from typing import Dict, Tuple

from Infrastructure.DataTypes.Verification.OutputStructures.AbstractOutputStrucutre import AbstractOutputStructure
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.Assignment import Assignment
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.Proposition import Proposition
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.VariableOrder import VariableOrdering


class Verdicts(AbstractOutputStructure):
    def __init__(self, variable_order: VariableOrdering):
        self.verdict = list()
        self.tp_to_ts = dict()
        self.variable_order = variable_order

    def retrieve_order(self):
        return self.variable_order.retrieve_order()

    def as_oracle(self, other: 'AbstractOutputStructure') -> Tuple[bool, str]:
        from Infrastructure.DataTypes.Verification.OutputStructures.Compare.VerdictsComparator import as_oracle
        return as_oracle(self, other)

    def retrieve(self, time_point):
        # Entries are stored as (time_stamp, time_point, values); match on the
        # TIMEPOINT (second element). The old unpacking matched on the
        # timestamp, which only worked by coincidence on traces with ts == tp
        # and otherwise silently skipped the value-level comparison
        # (both sides returned None for every timepoint).
        for (_, tp, val) in self.verdict:
            if tp == time_point:
                return self.tp_to_ts[time_point], time_point, val
        return None

    def time_points(self) -> Dict[int, int]:
        return self.tp_to_ts

    def insert(self, value, time_point, time_stamp):
        self.tp_to_ts[time_point] = time_stamp
        if not self.variable_order.retrieve_order():
            values = [Proposition(True)]  # needs to consider negation eventually
        else:
            values = value if isinstance(value, list) else [value]
            values = list(map(lambda va: Assignment(va, self.variable_order), values))
        self.verdict.append((time_stamp, time_point, values))
