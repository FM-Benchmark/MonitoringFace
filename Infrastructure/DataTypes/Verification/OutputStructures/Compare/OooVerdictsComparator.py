from typing import Tuple

from Infrastructure.DataTypes.Verification.OutputStructures.AbstractComparator import time_point_pdt_check, verdicts_to_proposition_tree, verdicts_to_prop_list_inner, \
    verdicts_to_verdicts_inner
from Infrastructure.DataTypes.Verification.OutputStructures.AbstractOutputStrucutre import AbstractOutputStructure
from Infrastructure.DataTypes.Verification.OutputStructures.PDTHelper import equality_between_pdts
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.OooVerdicts import OooVerdicts
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.PropositionList import PropositionList
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.PropositionTree import PropositionTree
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.Verdicts import Verdicts


def as_oracle(verdict: OooVerdicts, other: AbstractOutputStructure) -> Tuple[bool, str]:
    if isinstance(other, Verdicts):
        return ooo_verdicts_to_verdicts_comp(verdict, other)
    elif isinstance(other, OooVerdicts):
        return ooo_verdicts_to_ooo_verdicts_comp(verdict, other)
    elif isinstance(other, PropositionTree):
        return ooo_verdicts_to_proposition_tree_comp(verdict, other)
    elif isinstance(other, PropositionList):
        return ooo_verdicts_to_proposition_list_comp(verdict, other)
    else:
        raise Exception(f"Unknown type compare with type {other}")


def ooo_verdicts_to_ooo_verdicts_comp(oracle: OooVerdicts, other: OooVerdicts) -> Tuple[bool, str]:
    return verdicts_to_verdicts_inner(oracle, other)


def ooo_verdicts_to_verdicts_comp(oracle: OooVerdicts, other: Verdicts) -> Tuple[bool, str]:
    return verdicts_to_verdicts_inner(oracle, other)


def ooo_verdicts_to_proposition_list_comp(oracle: OooVerdicts, other: PropositionList) -> Tuple[bool, str]:
    return verdicts_to_prop_list_inner(oracle, other)


def ooo_verdicts_to_proposition_tree_comp(oracle: OooVerdicts, other: PropositionTree) -> Tuple[bool, str]:
    (verdict, txt) = time_point_pdt_check(oracle, other)
    if not verdict: return False, txt

    oracle_pdt = verdicts_to_proposition_tree(oracle, other.variable_order)
    for tp in oracle.time_points():
        if not equality_between_pdts(oracle_pdt.retrieve_order(), oracle_pdt.forest[tp], other.forest[tp]):
            return False, "Verified: Structures are not equivalent"
    return True, "Verified"
