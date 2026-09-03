from typing import Tuple, List, Union

from Infrastructure.DataTypes.Verification.OutputStructures.AbstractOutputStrucutre import AbstractOutputStructure
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.OooVerdicts import OooVerdicts
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.PropositionList import PropositionList
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.PropositionTree import PDTLeaf, PDTComplementSet, PDTSet, PDTNode, PropositionTree, PDTTree
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.Verdicts import Verdicts
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.Assignment import Assignment
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.Proposition import Proposition
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.VariableOrder import VariableOrdering, \
    VariableOrder


def pdt_to_verdicts_inner(oracle: PropositionTree, other: Union[Verdicts, OooVerdicts]) -> Tuple[bool, str]:
    verdict, txt = time_point_pdt_check(oracle, other)
    if not verdict: return False, txt

    intersection_set = set(oracle.time_points().keys()) & set(other.time_points().keys())
    for tp in intersection_set:
        oracle_pdt = oracle.retrieve(tp)
        other_verdict = other.retrieve(tp)
        if other_verdict is None and oracle_pdt is None:
            continue
        elif other_verdict is None and oracle_pdt is not None:
            return False, f"Tool is missing verdict at time point {tp}"

        for _, _, verdicts in other_verdict:
            for v in verdicts:
                if not oracle_pdt.check_assignment(v):
                    return False, f"Tool has different verdict for {v} at time point {tp}"

    return True, "Check: Tool output is a subset"


def verdicts_to_verdicts_inner(oracle: Union[Verdicts, OooVerdicts], other: Union[OooVerdicts, Verdicts]) -> Tuple[bool, str]:
    (verdict, txt) = time_point_check(oracle, other)
    if not verdict: return False, txt

    for time_point in oracle.time_points().keys():
        oracle_val = oracle.retrieve(time_point)
        tuple_val = other.retrieve(time_point)

        if oracle_val is None and tuple_val is None:
            continue
        elif oracle_val is None and tuple_val is not None:
            return False, f"Tool has additional verdicts at time point {time_point}"
        elif oracle_val is not None and tuple_val is None:
            return False, f"Tool is missing verdicts at time point {time_point}"

        s_o_v = sorted(oracle_val[2])
        o_o_v = sorted(tuple_val[2])

        if s_o_v != o_o_v:
            return False, f"Verdict values differ at time point {oracle_val[1]} =>\nOracle {oracle_val[2]}\nTool {tuple_val[2]}"
    return True, "Verified"


def verdicts_to_prop_list_inner(oracle: Union[Verdicts, OooVerdicts], other: PropositionList) -> Tuple[bool, str]:
    (verdict, txt) = time_point_check(oracle, other)
    if not verdict: return False, txt

    for time_point in oracle.time_points().keys():
        oracle_val = oracle.retrieve(time_point)
        other_val = other.retrieve(time_point)

        if oracle_val is None and other_val is None:
            continue
        elif oracle_val is None and other_val is not None:
            return False, f"Tool has additional verdicts at time point {time_point}"
        elif oracle_val is not None and other_val is None:
            return False, f"Tool is missing verdicts at time point {time_point}"
    return True, "Checked"


def time_point_check(oracle: AbstractOutputStructure, other: AbstractOutputStructure) -> Tuple[bool, str]:
    oracle_tps = set(oracle.time_points().keys())
    other_tps = set(other.time_points().keys())

    if oracle_tps != other_tps:
        missing_from_tool = oracle_tps - other_tps
        missing_from_oracle = other_tps - oracle_tps
        if missing_from_tool:
            return False, f"Tool is missing time points from oracle: {missing_from_tool}"
        if missing_from_oracle:
            return False, f"Oracle is missing time points from tool: {missing_from_oracle}"
    return True, "Verified"


def time_point_pdt_check(oracle: AbstractOutputStructure, other: AbstractOutputStructure) -> Tuple[bool, str]:
    oracle_tps = set(oracle.time_points().keys())
    other_tps = set(other.time_points().keys())

    complement = other_tps - oracle_tps
    for c_tp in complement:
        if not other.retrieve(c_tp).is_false_leave():
            return False, f"PropositionTree has verdicts at time point {c_tp}"
    return True, "Verified"


def time_point_pdt_pdt_check(oracle: AbstractOutputStructure, other: AbstractOutputStructure) -> Tuple[bool, str]:
    oracle_tps = set(oracle.time_points())
    other_tps = set(other.time_points())

    if oracle_tps != other_tps:
        missing_from_tool = set(oracle_tps) - set(other_tps)
        missing_from_oracle = set(other_tps) - set(oracle_tps)
        if missing_from_tool:
            return False, f"Tool is missing time points from oracle: {missing_from_tool}"
        if missing_from_oracle:
            return False, f"Oracle is missing time points from tool: {missing_from_oracle}"
    return True, "Verified"


def verdicts_to_proposition_tree(verdicts: Union[Verdicts, OooVerdicts], new_order: VariableOrdering):
    values = []
    for tp in sorted(verdicts.time_points().keys()):
        ts, _, vals = verdicts.retrieve(tp)
        values.append([ts, tp, vals])

    pdt = PropositionTree(new_order)
    return to_tree_inner(values, pdt)


def to_tree_inner(values, pdt: PropositionTree):
    for (ts, tp, val) in values:
        pdt.tp_to_ts[tp] = ts
        if isinstance(val[0], Proposition):
            pdt.forest[tp] = PDTTree(PDTLeaf(value=val.value))
        else:
            assignments = list(map(lambda ass: ass.retrieve_order(new_order=pdt.variable_order), val))
            pdt.forest[tp] = PDTTree(_pdt_subtree_recurse(vars_=pdt.retrieve_order(), assignments=assignments))
    return pdt


def _pdt_subtree_recurse(vars_: List[str], assignments: List[Assignment]):
    if not vars_:
        return PDTLeaf(len(assignments) > 0)

    var_ = vars_[0]
    remaining = vars_[1:]

    value_to_assignments = {}
    for assignment in assignments:
        val = assignment.retrieve_value(var_)
        if val not in value_to_assignments:
            value_to_assignments[val] = []
        value_to_assignments[val].append(assignment)

    choices = []
    for elem, matching in value_to_assignments.items():
        subtree = _pdt_subtree_recurse(remaining, matching)
        choices.append((PDTSet({elem}), subtree))

    choices.append((PDTComplementSet(set(value_to_assignments.keys())), PDTLeaf(False)))
    return PDTNode(var_, choices)
