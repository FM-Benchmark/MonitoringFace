from typing import Tuple

from Infrastructure.DataTypes.Verification.OutputStructures.AbstractComparator import verdicts_to_proposition_tree, time_point_pdt_check, verdicts_to_verdicts_inner, \
    verdicts_to_prop_list_inner
from Infrastructure.DataTypes.Verification.OutputStructures.AbstractOutputStrucutre import AbstractOutputStructure
from Infrastructure.DataTypes.Verification.OutputStructures.PDTHelper import equality_between_pdts
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.OooVerdicts import OooVerdicts
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.PropositionList import PropositionList
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.PropositionTree import PropositionTree
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.Verdicts import Verdicts


def as_oracle(verdict: Verdicts, other: AbstractOutputStructure) -> Tuple[bool, str]:
    if isinstance(other, Verdicts):
        return verdicts_to_verdicts_comp(verdict, other)
    elif isinstance(other, OooVerdicts):
        return verdicts_to_ooo_verdicts_comp(verdict, other)
    elif isinstance(other, PropositionTree):
        return verdicts_to_proposition_tree_comp(verdict, other)
    elif isinstance(other, PropositionList):
        return verdicts_to_proposition_list_comp(verdict, other)
    else:
        raise Exception(f"Unknown type compare with type {other}")


def verdicts_to_verdicts_comp(oracle: Verdicts, other: Verdicts) -> Tuple[bool, str]:
    oracle_len = oracle.entry_count()
    other_len = other.entry_count()
    if oracle_len != other_len:
        return False, f"Verdict lengths differ! Oracle length: {oracle_len}, Tool length: {other_len}"
    return verdicts_to_verdicts_inner(oracle, other)


def verdicts_to_ooo_verdicts_comp(oracle: Verdicts, other: OooVerdicts) -> Tuple[bool, str]:
    return verdicts_to_verdicts_inner(oracle, other)


def verdicts_to_proposition_list_comp(oracle: Verdicts, other: PropositionList) -> Tuple[bool, str]:
    return verdicts_to_prop_list_inner(oracle, other)


def verdicts_to_proposition_tree_comp(oracle: Verdicts, other: PropositionTree) -> Tuple[bool, str]:
    (verdict, txt) = time_point_pdt_check(oracle, other)
    if not verdict: return False, txt

    oracle_pdt = verdicts_to_proposition_tree(oracle, other.variable_order)
    for tp in oracle.time_points().keys():
        if not equality_between_pdts(oracle_pdt.retrieve_order(), oracle_pdt.forest[tp], other.forest[tp]):
            return False, "Verified: Structures are not equivalent"
    return True, "Verified"
