"""Independent reference evaluator for the phase-0 MFOTL past fragment.

Used by the TeSSLa converter tests as a second opinion next to stored
VeriMon/MonPoly results.  Deliberately implemented differently from the
compiler: valuations are frozensets of (variable, value) pairs evaluated
directly from the semantics, not positional tuples through relational
operators, so column-order bugs in the compiler cannot cancel out here.

Per timepoint the evaluator runs two phases: first every subformula's
satisfying valuations are computed and memoized against the *old* register
state, then all registers are committed from the memo.  This keeps nested
temporal operators (e.g. PREVIOUS inside SINCE) from observing half-updated
state.
"""

import re
from typing import Dict, FrozenSet, List, Set, Tuple

from Archive.Implementations.Builders.ProcessorBuilder.PolicyConverters.TeSSLaPolicyConverter.mfotl2tessla import (
    And, Const, Eq, Exists, Formula, Not, Once, Or, Pred, Prev, Since, Var, _fv,
)

Valuation = FrozenSet[Tuple[str, int]]
Database = Dict[str, Set[Tuple[int, ...]]]
TracePoint = Tuple[int, int, Database]  # (tp, ts, relations)


def _match_pred(node: Pred, database: Database) -> Set[Valuation]:
    result: Set[Valuation] = set()
    for row in database.get(node.name, set()):
        if len(row) != len(node.args):
            continue
        binding: Dict[str, int] = {}
        ok = True
        for arg, value in zip(node.args, row):
            if isinstance(arg, Const):
                if arg.value != value:
                    ok = False
                    break
            else:
                if arg.name in binding and binding[arg.name] != value:
                    ok = False
                    break
                binding[arg.name] = value
        if ok:
            result.add(frozenset(binding.items()))
    return result


def _join(left: Set[Valuation], right: Set[Valuation]) -> Set[Valuation]:
    result: Set[Valuation] = set()
    for lv in left:
        ld = dict(lv)
        for rv in right:
            merged = dict(ld)
            compatible = True
            for var, val in rv:
                if var in merged and merged[var] != val:
                    compatible = False
                    break
                merged[var] = val
            if compatible:
                result.add(frozenset(merged.items()))
    return result


def _restrict(valuation: Valuation, variables: Set[str]) -> Valuation:
    return frozenset((var, val) for var, val in valuation if var in variables)


class RefEvaluator:
    """Evaluates one formula over one trace, timepoint by timepoint."""

    def __init__(self, formula: Formula):
        self.formula = formula
        self.prev_state: Dict[int, Set[Valuation]] = {}
        self.registers: Dict[int, Set[Valuation]] = {}
        self.memo: Dict[int, Set[Valuation]] = {}
        self.first = True

    def run(self, trace: List[TracePoint]) -> List[Tuple[int, Set[Valuation]]]:
        results = []
        for tp, _ts, database in trace:
            self.memo = {}
            sat = self._eval(self.formula, database)
            self._commit(self.formula)
            results.append((tp, sat))
            self.first = False
        return results

    def _eval(self, node: Formula, db: Database) -> Set[Valuation]:
        key = id(node)
        if key in self.memo:
            return self.memo[key]
        value = self._eval_inner(node, db)
        self.memo[key] = value
        return value

    def _eval_inner(self, node: Formula, db: Database) -> Set[Valuation]:
        if isinstance(node, Pred):
            return _match_pred(node, db)
        if isinstance(node, Eq):
            terms = (node.left, node.right)
            consts = [t.value for t in terms if isinstance(t, Const)]
            variables = [t.name for t in terms if isinstance(t, Var)]
            if len(variables) == 1:
                return {frozenset({(variables[0], consts[0])})}
            return {frozenset()} if consts[0] == consts[1] else set()
        if isinstance(node, Not):
            return set() if self._eval(node.sub, db) else {frozenset()}
        if isinstance(node, And):
            left, right = node.left, node.right
            if isinstance(left, Not) and _fv(left.sub) and not (
                isinstance(right, Not) and _fv(right.sub)
            ):
                left, right = right, left
            if isinstance(right, Not) and _fv(right.sub):
                pos = self._eval(left, db)
                neg = self._eval(right.sub, db)
                neg_vars = _fv(right.sub)
                return {v for v in pos if _restrict(v, neg_vars) not in neg}
            return _join(self._eval(left, db), self._eval(right, db))
        if isinstance(node, Or):
            return self._eval(node.left, db) | self._eval(node.right, db)
        if isinstance(node, Exists):
            sub = self._eval(node.sub, db)
            keep = _fv(node.sub) - set(node.variables)
            return {_restrict(v, keep) for v in sub}
        if isinstance(node, Prev):
            # Also evaluate the child so its own registers commit this tp.
            self._eval(node.sub, db)
            if self.first:
                return set()
            return self.prev_state.get(id(node), set())
        if isinstance(node, Once):
            current = self._eval(node.sub, db)
            return self.registers.get(id(node), set()) | current
        if isinstance(node, Since):
            alpha = node.left
            negated = isinstance(alpha, Not) and bool(_fv(alpha.sub))
            alpha_eval = alpha.sub if negated else alpha
            alpha_now = self._eval(alpha_eval, db)
            beta_now = self._eval(node.right, db)
            alpha_vars = _fv(alpha_eval)
            carried = set()
            for v in self.registers.get(id(node), set()):
                inside = _restrict(v, alpha_vars) in alpha_now
                if inside != negated:
                    carried.add(v)
            return beta_now | carried
        raise ValueError(f"Unsupported node {type(node).__name__}")

    def _commit(self, node: Formula):
        """Roll registers forward from the memo (all values pre-commit)."""
        if isinstance(node, (Pred, Eq)):
            return
        if isinstance(node, Not):
            self._commit(node.sub)
            return
        if isinstance(node, (And, Or)):
            self._commit(node.left)
            self._commit(node.right)
            return
        if isinstance(node, Exists):
            self._commit(node.sub)
            return
        if isinstance(node, Prev):
            self._commit(node.sub)
            self.prev_state[id(node)] = self.memo[id(node.sub)]
            return
        if isinstance(node, Once):
            self._commit(node.sub)
            self.registers[id(node)] = self.memo[id(node)]
            return
        if isinstance(node, Since):
            alpha = node.left.sub if (
                isinstance(node.left, Not) and _fv(node.left.sub)
            ) else node.left
            self._commit(alpha)
            self._commit(node.right)
            self.registers[id(node)] = self.memo[id(node)]
            return
        raise ValueError(f"Unsupported node {type(node).__name__}")


_ROW_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*tp\s*=\s*(\d+)\s*,\s*ts\s*=\s*(\d+)\s*(.*)$"
)
_ARG_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*=\s*(-?\d+)")


def parse_csv_trace(lines: List[str]) -> List[TracePoint]:
    trace: List[TracePoint] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        match = _ROW_RE.match(line)
        if not match:
            raise ValueError(f"Bad CSV row: {line[:60]!r}")
        predicate, tp, ts = match.group(1), int(match.group(2)), int(match.group(3))
        values = tuple(int(m.group(1)) for m in _ARG_RE.finditer(match.group(4)))
        if not trace or trace[-1][0] != tp:
            trace.append((tp, ts, {}))
        trace[-1][2].setdefault(predicate, set()).add(values)
    return trace


def satisfied_timepoints(formula: Formula, trace: List[TracePoint]) -> Set[int]:
    """Timepoints where the existential closure of the formula holds."""
    return {tp for tp, valuations in RefEvaluator(formula).run(trace) if valuations}
