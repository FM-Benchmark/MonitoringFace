"""MFOTL -> TeSSLa compiler (phase 0: closed past-only formulas, intervals [0,*)).

Compiles a MonPoly-syntax MFOTL policy into a self-contained TeSSLa
specification over the encoding:

  * TeSSLa time axis   = timepoint index (the CSV ``tp`` field)
  * timestamps         = data, carried on the input stream ``mf_ts`` (ticks at
    every timepoint, so empty databases stay visible)
  * relation per predicate per timepoint = ONE Set[List[Int]]-valued event on
    ``mf_p_<Pred>`` (absent event = empty relation, restored via merge)
  * every subformula   = one Set[List[Int]]-valued stream ticking at every
    timepoint, columns in sorted-variable-name order
  * verdict            = ``out mf_v`` (Events[Bool], one event per timepoint;
    true iff the existentially closed formula holds there)

The generated specification is delay-free.  Supported fragment (hard error on
anything else, following the QTLConverter precedent of rejecting rather than
approximating): predicates over int arguments, AND / OR / NOT, EXISTS,
var = const equalities, PREVIOUS[0,*), ONCE[0,*), SINCE[0,*) (also with a
negated left-hand side), all under the MonPoly-style safety conditions that
keep every subformula relation finite.
"""

import re
from typing import Dict, List, Optional, Tuple


class UnsupportedFragmentError(Exception):
    """The policy parses but lies outside the phase-0 fragment."""


class PolicyParseError(Exception):
    pass


# --- AST ---------------------------------------------------------------------

class Term:
    pass


class Var(Term):
    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return self.name


class Const(Term):
    def __init__(self, value: int):
        self.value = value

    def __repr__(self):
        return str(self.value)


class Formula:
    pass


class Pred(Formula):
    def __init__(self, name: str, args: List[Term]):
        self.name = name
        self.args = args


class Eq(Formula):
    def __init__(self, left: Term, right: Term):
        self.left = left
        self.right = right


class Not(Formula):
    def __init__(self, sub: Formula):
        self.sub = sub


class And(Formula):
    def __init__(self, left: Formula, right: Formula):
        self.left = left
        self.right = right


class Or(Formula):
    def __init__(self, left: Formula, right: Formula):
        self.left = left
        self.right = right


class Exists(Formula):
    def __init__(self, variables: List[str], sub: Formula):
        self.variables = variables
        self.sub = sub


class Interval:
    def __init__(self, low: int, high: Optional[int]):
        self.low = low
        self.high = high  # None = unbounded (*)

    def is_zero_unbounded(self) -> bool:
        return self.low == 0 and self.high is None

    def __repr__(self):
        return f"[{self.low},{'*' if self.high is None else self.high})"


class Prev(Formula):
    def __init__(self, interval: Interval, sub: Formula):
        self.interval = interval
        self.sub = sub


class Once(Formula):
    def __init__(self, interval: Interval, sub: Formula):
        self.interval = interval
        self.sub = sub


class Since(Formula):
    def __init__(self, interval: Interval, left: Formula, right: Formula):
        self.interval = interval
        self.left = left
        self.right = right


# --- Tokenizer / parser ------------------------------------------------------

_TOKEN_RE = re.compile(
    r"\s*(?:"
    r"(?P<lparen>\()|(?P<rparen>\))|"
    r"(?P<lbrack>\[)|(?P<rbrack>[\])])|"
    r"(?P<comma>,)|(?P<dot>\.)|(?P<eq>=)|(?P<star>\*)|"
    r"(?P<int>-?\d+)|"
    r"(?P<ident>[A-Za-z_][A-Za-z0-9_]*)"
    r")"
)

_KEYWORDS = {
    "AND", "OR", "NOT", "EXISTS", "FORALL", "IMPLIES", "TRUE", "FALSE",
    "PREVIOUS", "NEXT", "ONCE", "EVENTUALLY", "ALWAYS", "HISTORICALLY",
    "SINCE", "UNTIL", "PREV",
}

# Parsed so the rejection message can name them instead of failing mid-parse.
_FUTURE_OR_UNSUPPORTED_UNARY = {"NEXT", "EVENTUALLY", "ALWAYS", "HISTORICALLY"}


def _tokenize(text: str) -> List[Tuple[str, str]]:
    tokens = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if not match or match.end() == match.start():
            remainder = text[pos:].strip()
            if not remainder:
                break
            raise PolicyParseError(f"Cannot tokenize policy at: {remainder[:40]!r}")
        pos = match.end()
        kind = match.lastgroup
        value = match.group(kind)
        tokens.append((kind, value))
    return tokens


class _Parser:
    """Recursive descent over the MonPoly-ish syntax emitted by gen_fma.

    Precedence (loose to tight): SINCE/UNTIL, OR, AND, unary (NOT, EXISTS,
    PREVIOUS, ONCE, ...).  EXISTS scopes maximally to the right, matching
    MonPoly/VeriMon; gen_fma parenthesizes every scope anyway.
    """

    def __init__(self, tokens: List[Tuple[str, str]]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Optional[Tuple[str, str]]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> Tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise PolicyParseError("Unexpected end of policy")
        self.pos += 1
        return tok

    def expect(self, kind: str, value: Optional[str] = None) -> str:
        tok = self.next()
        if tok[0] != kind or (value is not None and tok[1] != value):
            raise PolicyParseError(f"Expected {value or kind}, found {tok[1]!r}")
        return tok[1]

    def at_keyword(self, *names: str) -> bool:
        tok = self.peek()
        return tok is not None and tok[0] == "ident" and tok[1] in names

    def parse_formula(self) -> Formula:
        left = self.parse_or()
        if self.at_keyword("SINCE"):
            self.next()
            interval = self.parse_interval()
            right = self.parse_or()
            return Since(interval, left, right)
        if self.at_keyword("UNTIL"):
            raise UnsupportedFragmentError(
                "UNTIL is a future operator; phase 0 supports the past-only fragment"
            )
        if self.at_keyword("IMPLIES"):
            raise UnsupportedFragmentError(
                "IMPLIES is not in the phase-0 fragment (rewrite as NOT/OR)"
            )
        return left

    def parse_or(self) -> Formula:
        left = self.parse_and()
        while self.at_keyword("OR"):
            self.next()
            left = Or(left, self.parse_and())
        return left

    def parse_and(self) -> Formula:
        left = self.parse_unary()
        while self.at_keyword("AND"):
            self.next()
            left = And(left, self.parse_unary())
        return left

    def parse_interval(self) -> Interval:
        self.expect("lbrack")
        low = int(self.expect("int"))
        self.expect("comma")
        tok = self.next()
        if tok[0] == "star":
            high = None
        elif tok[0] == "int":
            high = int(tok[1])
        else:
            raise PolicyParseError(f"Bad interval bound: {tok[1]!r}")
        closing = self.next()
        if closing[0] not in ("rbrack", "rparen"):
            raise PolicyParseError(f"Expected interval close, found {closing[1]!r}")
        return Interval(low, high)

    def parse_unary(self) -> Formula:
        tok = self.peek()
        if tok is None:
            raise PolicyParseError("Unexpected end of policy")
        kind, value = tok
        if kind == "ident" and value in _KEYWORDS:
            if value == "NOT":
                self.next()
                return Not(self.parse_unary())
            if value in ("EXISTS", "FORALL"):
                if value == "FORALL":
                    raise UnsupportedFragmentError(
                        "FORALL is not in the phase-0 fragment"
                    )
                self.next()
                variables = [self._quantifier_variable()]
                while self.peek() and self.peek()[0] == "comma":
                    self.next()
                    variables.append(self._quantifier_variable())
                self.expect("dot")
                # MonPoly scopes quantifiers maximally to the right.
                return Exists(variables, self.parse_formula())
            if value in ("PREVIOUS", "PREV"):
                self.next()
                interval = self.parse_interval()
                return Prev(interval, self.parse_unary())
            if value == "ONCE":
                self.next()
                interval = self.parse_interval()
                return Once(interval, self.parse_unary())
            if value in _FUTURE_OR_UNSUPPORTED_UNARY:
                raise UnsupportedFragmentError(
                    f"{value} is not in the phase-0 fragment (past-only, [0,*))"
                )
            if value in ("TRUE", "FALSE"):
                raise UnsupportedFragmentError(
                    "TRUE/FALSE literals are not in the phase-0 fragment"
                )
            raise PolicyParseError(f"Unexpected keyword {value!r}")
        if kind == "lparen":
            self.next()
            inner = self.parse_formula()
            self.expect("rparen")
            return inner
        if kind in ("ident", "int"):
            return self.parse_atom()
        raise PolicyParseError(f"Unexpected token {value!r}")

    def _quantifier_variable(self) -> str:
        name = self.expect("ident")
        if name in _KEYWORDS:
            raise PolicyParseError(f"Cannot bind the keyword {name!r} as a variable")
        return name

    def parse_term(self) -> Term:
        tok = self.next()
        if tok[0] == "int":
            return Const(int(tok[1]))
        if tok[0] == "ident" and tok[1] not in _KEYWORDS:
            return Var(tok[1])
        raise PolicyParseError(f"Expected a term, found {tok[1]!r}")

    def parse_atom(self) -> Formula:
        tok = self.peek()
        if tok[0] == "ident" and tok[1] not in _KEYWORDS:
            # Lookahead: predicate application vs equality over a variable.
            after = self.tokens[self.pos + 1] if self.pos + 1 < len(self.tokens) else None
            if after is not None and after[0] == "lparen":
                name = self.next()[1]
                self.expect("lparen")
                args: List[Term] = []
                if self.peek() and self.peek()[0] != "rparen":
                    args.append(self.parse_term())
                    while self.peek() and self.peek()[0] == "comma":
                        self.next()
                        args.append(self.parse_term())
                self.expect("rparen")
                return Pred(name, args)
        left = self.parse_term()
        self.expect("eq")
        right = self.parse_term()
        return Eq(left, right)


def parse_policy(text: str) -> Formula:
    parser = _Parser(_tokenize(text))
    formula = parser.parse_formula()
    if parser.peek() is not None:
        raise PolicyParseError(
            f"Trailing input after formula: {parser.peek()[1]!r}"
        )
    return formula


# --- Signature ---------------------------------------------------------------

_SIG_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*$")
_TESSLA_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_signature(text: str) -> Dict[str, int]:
    """Signature file -> {predicate: arity}.  Phase 0 accepts int columns only."""
    arities: Dict[str, int] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _SIG_LINE_RE.match(line)
        if not match:
            raise UnsupportedFragmentError(f"Cannot parse signature line: {line!r}")
        name, cols = match.group(1), match.group(2).strip()
        if not _TESSLA_ID_RE.match(name):
            raise UnsupportedFragmentError(
                f"Predicate name {name!r} is not a valid TeSSLa identifier"
            )
        if name in arities:
            raise UnsupportedFragmentError(
                f"Predicate {name} declared twice in the signature"
            )
        if cols:
            col_types = [c.strip() for c in cols.split(",")]
            for col in col_types:
                type_name = col.split(":")[-1].strip().lower() if ":" in col else col.lower()
                if type_name != "int":
                    raise UnsupportedFragmentError(
                        f"Signature column {col!r} of {name}: phase 0 supports int "
                        f"columns only (TeSSLa prints strings unquoted, so string "
                        f"verdicts cannot be re-parsed reliably)"
                    )
            arities[name] = len(col_types)
        else:
            arities[name] = 0
    return arities


# --- Safety analysis ---------------------------------------------------------

def free_vars(formula: Formula) -> List[str]:
    """Sorted free variables; also the column order of the compiled stream."""
    return sorted(_fv(formula))


def _fv(formula: Formula) -> set:
    if isinstance(formula, Pred):
        return {a.name for a in formula.args if isinstance(a, Var)}
    if isinstance(formula, Eq):
        return {t.name for t in (formula.left, formula.right) if isinstance(t, Var)}
    if isinstance(formula, Not):
        return _fv(formula.sub)
    if isinstance(formula, (And, Or, Since)):
        return _fv(formula.left) | _fv(formula.right)
    if isinstance(formula, Exists):
        return _fv(formula.sub) - set(formula.variables)
    if isinstance(formula, (Prev, Once)):
        return _fv(formula.sub)
    raise UnsupportedFragmentError(f"Unknown formula node {type(formula).__name__}")


def _require_zero_unbounded(interval: Interval, operator: str):
    if not interval.is_zero_unbounded():
        raise UnsupportedFragmentError(
            f"{operator}{interval}: phase 0 supports the interval [0,*) only"
        )


def check_safety(formula: Formula):
    """Reject formulas outside the finitely-evaluable phase-0 fragment.

    Mirrors the relevant part of MonPoly's monitorable fragment: every
    compiled subformula must denote a finite relation at each timepoint.
    """
    if isinstance(formula, Pred):
        return
    if isinstance(formula, Eq):
        left_const = isinstance(formula.left, Const)
        right_const = isinstance(formula.right, Const)
        if not (left_const or right_const):
            raise UnsupportedFragmentError(
                f"Equality {formula.left} = {formula.right} between two free "
                f"variables denotes an infinite relation; phase 0 requires one "
                f"side to be a constant"
            )
        return
    if isinstance(formula, Not):
        if _fv(formula.sub):
            raise UnsupportedFragmentError(
                f"NOT over a subformula with free variables "
                f"({', '.join(sorted(_fv(formula.sub)))}) denotes an infinite "
                f"relation; only guarded negation (AND NOT with covered "
                f"variables) or closed negation is supported"
            )
        check_safety(formula.sub)
        return
    if isinstance(formula, And):
        left, right = formula.left, formula.right
        # Normalize: a guarded negation may sit on either side.
        if isinstance(left, Not) and _fv(left.sub) and not (
            isinstance(right, Not) and _fv(right.sub)
        ):
            left, right = right, left
        if isinstance(right, Not) and _fv(right.sub):
            if not _fv(right.sub) <= _fv(left):
                raise UnsupportedFragmentError(
                    f"Anti-join AND NOT: variables of the negated side "
                    f"({', '.join(sorted(_fv(right.sub)))}) must be covered by "
                    f"the positive side ({', '.join(sorted(_fv(left)))})"
                )
            check_safety(left)
            check_safety(right.sub)
            return
        check_safety(left)
        check_safety(right)
        return
    if isinstance(formula, Or):
        if _fv(formula.left) != _fv(formula.right):
            raise UnsupportedFragmentError(
                f"OR requires identical free variables on both sides, got "
                f"{sorted(_fv(formula.left))} vs {sorted(_fv(formula.right))}"
            )
        check_safety(formula.left)
        check_safety(formula.right)
        return
    if isinstance(formula, Exists):
        check_safety(formula.sub)
        return
    if isinstance(formula, Prev):
        _require_zero_unbounded(formula.interval, "PREVIOUS")
        check_safety(formula.sub)
        return
    if isinstance(formula, Once):
        _require_zero_unbounded(formula.interval, "ONCE")
        check_safety(formula.sub)
        return
    if isinstance(formula, Since):
        _require_zero_unbounded(formula.interval, "SINCE")
        alpha = formula.left
        if isinstance(alpha, Not):
            alpha_pos = alpha.sub
        else:
            alpha_pos = alpha
        if not _fv(alpha_pos) <= _fv(formula.right):
            raise UnsupportedFragmentError(
                f"SINCE: variables of the left-hand side "
                f"({', '.join(sorted(_fv(alpha_pos)))}) must be covered by the "
                f"right-hand side ({', '.join(sorted(_fv(formula.right)))})"
            )
        check_safety(alpha_pos)
        check_safety(formula.right)
        return
    raise UnsupportedFragmentError(f"Unsupported construct {type(formula).__name__}")


# --- Code generation ---------------------------------------------------------

SET_T = "Set[List[Int]]"
EV_SET_T = f"Events[{SET_T}]"
EMPTY_SET = "Set.empty[List[Int]]"


def _list_expr(elements: List[str]) -> str:
    """Build a List[Int] value expression from element expressions."""
    expr = "List.empty[Int]"
    for element in elements:
        expr = f"List.append({expr}, {element})"
    return expr


def _tuple_from(source: str, indices: List[int]) -> str:
    return _list_expr([f"List.get({source}, {i})" for i in indices])


class _CodeGen:
    def __init__(self, arities: Dict[str, int]):
        self.arities = arities
        self.lines: List[str] = []
        self.counter = 0

    def fresh(self) -> str:
        self.counter += 1
        return f"mf_s{self.counter}"

    def emit(self, name: str, body: str):
        self.lines.append(f"def {name}: {EV_SET_T} = {body}")

    # Every compile_* returns (stream_name, columns); the stream ticks at every
    # timepoint and holds the subformula's relation with the given column order.
    def compile(self, formula: Formula) -> Tuple[str, List[str]]:
        if isinstance(formula, Pred):
            return self.compile_pred(formula)
        if isinstance(formula, Eq):
            return self.compile_eq(formula)
        if isinstance(formula, Not):
            return self.compile_closed_not(formula)
        if isinstance(formula, And):
            return self.compile_and(formula)
        if isinstance(formula, Or):
            return self.compile_or(formula)
        if isinstance(formula, Exists):
            return self.compile_exists(formula)
        if isinstance(formula, Prev):
            return self.compile_prev(formula)
        if isinstance(formula, Once):
            return self.compile_once(formula)
        if isinstance(formula, Since):
            return self.compile_since(formula)
        raise UnsupportedFragmentError(f"Unsupported construct {type(formula).__name__}")

    def compile_pred(self, formula: Pred) -> Tuple[str, List[str]]:
        if formula.name not in self.arities:
            raise UnsupportedFragmentError(
                f"Predicate {formula.name} is not declared in the signature"
            )
        if self.arities[formula.name] != len(formula.args):
            raise UnsupportedFragmentError(
                f"Predicate {formula.name} used with arity {len(formula.args)}, "
                f"signature says {self.arities[formula.name]}"
            )
        columns = free_vars(formula)
        base = f"merge(mf_p_{formula.name}, mf_tick)"
        # Column i of the raw tuple corresponds to argument i.  The compiled
        # stream needs tuples over `columns` (sorted var names), filtered by
        # constant arguments and repeated-variable equalities.  The arity
        # guard comes first: a hand-written srv trace can carry rows of the
        # wrong length, and the short-circuit keeps List.get in range.
        conditions: List[str] = [f"List.size(t) == {len(formula.args)}"]
        first_pos: Dict[str, int] = {}
        for position, arg in enumerate(formula.args):
            if isinstance(arg, Const):
                conditions.append(f"List.get(t, {position}) == {arg.value}")
            else:
                if arg.name in first_pos:
                    conditions.append(
                        f"List.get(t, {position}) == List.get(t, {first_pos[arg.name]})"
                    )
                else:
                    first_pos[arg.name] = position
        name = self.fresh()
        out_tuple = _tuple_from("t", [first_pos[c] for c in columns])
        condition = " && ".join(conditions)
        body = (
            f"slift1({base}, (s: {SET_T}) => "
            f"Set.fold(s, {EMPTY_SET}, (acc: {SET_T}, t: List[Int]) => "
            f"if {condition} then Set.add(acc, {out_tuple}) else acc))"
        )
        self.emit(name, body)
        return name, columns

    def compile_eq(self, formula: Eq) -> Tuple[str, List[str]]:
        terms = (formula.left, formula.right)
        constants = [t for t in terms if isinstance(t, Const)]
        variables = [t for t in terms if isinstance(t, Var)]
        name = self.fresh()
        if len(variables) == 1:
            # var = const: the constant singleton relation {[c]} over the var.
            singleton = f"Set.add({EMPTY_SET}, {_list_expr([str(constants[0].value)])})"
            self.emit(name, f"const({singleton}, mf_ts)")
            return name, [variables[0].name]
        # const = const: the 0-ary constant relation.
        value = (
            f"Set.add({EMPTY_SET}, List.empty[Int])"
            if constants[0].value == constants[1].value
            else EMPTY_SET
        )
        self.emit(name, f"const({value}, mf_ts)")
        return name, []

    def compile_closed_not(self, formula: Not) -> Tuple[str, List[str]]:
        sub_name, _ = self.compile(formula.sub)
        name = self.fresh()
        body = (
            f"slift1({sub_name}, (s: {SET_T}) => "
            f"if Set.size(s) == 0 then Set.add({EMPTY_SET}, List.empty[Int]) "
            f"else {EMPTY_SET})"
        )
        self.emit(name, body)
        return name, []

    def compile_and(self, formula: And) -> Tuple[str, List[str]]:
        left, right = formula.left, formula.right
        if isinstance(left, Not) and _fv(left.sub) and not (
            isinstance(right, Not) and _fv(right.sub)
        ):
            left, right = right, left
        if isinstance(right, Not) and _fv(right.sub):
            return self.compile_antijoin(left, right.sub)
        return self.compile_join(left, right)

    def compile_join(self, left: Formula, right: Formula) -> Tuple[str, List[str]]:
        left_name, left_cols = self.compile(left)
        right_name, right_cols = self.compile(right)
        columns = sorted(set(left_cols) | set(right_cols))
        shared = [c for c in columns if c in left_cols and c in right_cols]
        conditions = [
            f"List.get(x, {left_cols.index(c)}) == List.get(y, {right_cols.index(c)})"
            for c in shared
        ]
        condition = " && ".join(conditions) if conditions else "true"
        merged = _list_expr(
            [
                f"List.get(x, {left_cols.index(c)})"
                if c in left_cols
                else f"List.get(y, {right_cols.index(c)})"
                for c in columns
            ]
        )
        name = self.fresh()
        body = (
            f"slift({left_name}, {right_name}, (a: {SET_T}, b: {SET_T}) => "
            f"Set.fold(a, {EMPTY_SET}, (acc: {SET_T}, x: List[Int]) => "
            f"Set.fold(b, acc, (acc2: {SET_T}, y: List[Int]) => "
            f"if {condition} then Set.add(acc2, {merged}) else acc2)))"
        )
        self.emit(name, body)
        return name, columns

    def compile_antijoin(self, left: Formula, negated: Formula) -> Tuple[str, List[str]]:
        left_name, left_cols = self.compile(left)
        right_name, right_cols = self.compile(negated)
        projection = _tuple_from("x", [left_cols.index(c) for c in right_cols])
        name = self.fresh()
        body = (
            f"slift({left_name}, {right_name}, (a: {SET_T}, b: {SET_T}) => "
            f"Set.fold(a, {EMPTY_SET}, (acc: {SET_T}, x: List[Int]) => "
            f"if Set.contains(b, {projection}) then acc else Set.add(acc, x)))"
        )
        self.emit(name, body)
        return name, left_cols

    def compile_or(self, formula: Or) -> Tuple[str, List[str]]:
        left_name, left_cols = self.compile(formula.left)
        right_name, _ = self.compile(formula.right)
        name = self.fresh()
        body = (
            f"slift({left_name}, {right_name}, (a: {SET_T}, b: {SET_T}) => "
            f"Set.union(a, b))"
        )
        self.emit(name, body)
        return name, left_cols

    def compile_exists(self, formula: Exists) -> Tuple[str, List[str]]:
        sub_name, sub_cols = self.compile(formula.sub)
        columns = [c for c in sub_cols if c not in formula.variables]
        if columns == sub_cols:
            # Vacuous quantifier: nothing to project away.
            return sub_name, sub_cols
        projection = _tuple_from("t", [sub_cols.index(c) for c in columns])
        name = self.fresh()
        body = (
            f"slift1({sub_name}, (s: {SET_T}) => "
            f"Set.map(s, (t: List[Int]) => {projection}))"
        )
        self.emit(name, body)
        return name, columns

    def compile_prev(self, formula: Prev) -> Tuple[str, List[str]]:
        sub_name, sub_cols = self.compile(formula.sub)
        name = self.fresh()
        # merge with mf_tick, NOT default(..): default would anchor the
        # "no previous timepoint" event at TeSSLa time 0, which is a phantom
        # timepoint whenever the trace does not start at tp 0.  merge ticks
        # exactly on real timepoints (last wins over the empty tick once a
        # previous value exists; both fire on the same mf_ts event).
        self.emit(name, f"merge(last({sub_name}, mf_ts), mf_tick)")
        return name, sub_cols

    def compile_once(self, formula: Once) -> Tuple[str, List[str]]:
        sub_name, sub_cols = self.compile(formula.sub)
        name = self.fresh()
        self.emit(f"{name}_prev", f"merge(last({name}, mf_ts), mf_tick)")
        body = (
            f"slift({name}_prev, {sub_name}, (p: {SET_T}, c: {SET_T}) => "
            f"Set.union(p, c))"
        )
        self.emit(name, body)
        return name, sub_cols

    def compile_since(self, formula: Since) -> Tuple[str, List[str]]:
        alpha = formula.left
        negated = isinstance(alpha, Not) and bool(_fv(alpha.sub))
        alpha_pos = alpha.sub if isinstance(alpha, Not) else alpha
        if isinstance(alpha, Not) and not _fv(alpha.sub):
            # Closed negation compiles as a regular 0-ary node.
            alpha_pos = alpha
            negated = False
        alpha_name, alpha_cols = self.compile(alpha_pos)
        beta_name, beta_cols = self.compile(formula.right)
        projection = _tuple_from("t", [beta_cols.index(c) for c in alpha_cols])
        name = self.fresh()
        self.emit(f"{name}_prev", f"merge(last({name}, mf_ts), mf_tick)")
        if negated:
            keep = (
                f"if Set.contains(a, {projection}) then acc else Set.add(acc, t)"
            )
        else:
            keep = (
                f"if Set.contains(a, {projection}) then Set.add(acc, t) else acc"
            )
        self.emit(
            f"{name}_keep",
            f"slift({name}_prev, {alpha_name}, (p: {SET_T}, a: {SET_T}) => "
            f"Set.fold(p, {EMPTY_SET}, (acc: {SET_T}, t: List[Int]) => {keep}))",
        )
        body = (
            f"slift({beta_name}, {name}_keep, (b: {SET_T}, k: {SET_T}) => "
            f"Set.union(b, k))"
        )
        self.emit(name, body)
        return name, beta_cols


def compile_policy(
    policy_text: str,
    signature_text: str,
    debug_set_output: bool = False,
    source_negated: bool = False,
) -> str:
    """Compile a phase-0 MFOTL policy + signature into a TeSSLa specification.

    ``source_negated`` marks NEGATED_MFOTL input, i.e. a file containing
    ``NOT (phi)`` produced by the negation plumbing.  Framework convention
    (the DejaVu chain sets the precedent): a tool consuming the negated
    policy must still report the timepoints where the ORIGINAL policy's
    existential closure holds, so the wrapper NOT is stripped and phi is
    compiled for satisfaction; no verdict inversion.  On plain MFOTL input a
    top-level NOT over an open formula is rejected, matching MonPoly's
    monitorability check.
    """
    formula = parse_policy(policy_text.strip())
    if source_negated:
        if isinstance(formula, Not):
            formula = formula.sub
    elif isinstance(formula, Not) and _fv(formula.sub):
        raise UnsupportedFragmentError(
            "Top-level NOT over an open formula denotes an infinite relation "
            "(MonPoly rejects it too); route the negated-policy convention "
            "through the NEGATED_MFOTL format instead"
        )
    check_safety(formula)
    arities = parse_signature(signature_text)

    gen = _CodeGen(arities)
    root_name, root_cols = gen.compile(formula)

    header = [
        "-- Generated by MonitoringFace TeSSLaPolicyConverter (phase 0).",
        "-- Encoding: TeSSLa time = timepoint index; mf_ts carries timestamps;",
        "-- one Set[List[Int]] event per predicate per timepoint.",
        "in mf_ts: Events[Int]",
    ]
    for predicate in sorted(arities):
        header.append(f"in mf_p_{predicate}: {EV_SET_T}")
    header.append(f"def mf_tick: {EV_SET_T} = const({EMPTY_SET}, mf_ts)")

    footer = []
    if root_cols:
        closure = (
            f"def mf_closed: {EV_SET_T} = slift1({root_name}, (s: {SET_T}) => "
            f"Set.map(s, (t: List[Int]) => List.empty[Int]))"
        )
        footer.append(closure)
        verdict_source = "mf_closed"
    else:
        verdict_source = root_name
    footer.append(
        f"def mf_v: Events[Bool] = slift1({verdict_source}, (s: {SET_T}) => "
        f"Set.size(s) > 0)"
    )
    footer.append("out mf_v")
    if debug_set_output:
        footer.append(f"out {root_name} as mf_set")
        footer.append(f"-- mf_set columns: {root_cols}")

    return "\n".join(header + gen.lines + footer) + "\n"


if __name__ == "__main__":
    import sys

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        print(
            "usage: python mfotl2tessla.py <signature.sig> <policy.policy> "
            "[--debug-set] [--negated]",
            file=sys.stderr,
        )
        sys.exit(2)
    with open(args[0]) as sig_file:
        signature = sig_file.read()
    with open(args[1]) as policy_file:
        policy = policy_file.read()
    print(
        compile_policy(
            policy,
            signature,
            debug_set_output="--debug-set" in sys.argv,
            source_negated="--negated" in sys.argv,
        ),
        end="",
    )
