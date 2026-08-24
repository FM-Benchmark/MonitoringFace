"""Tests for the phase-0 MFOTL -> TeSSLa converter chain. Plain asserts, no
pytest dependency: run with

    Infrastructure/environment/venv/bin/python -m Infrastructure.tests.test_tessla_converter

The end-to-end test needs the TeSSLa 2.1.0 interpreter jar and java on PATH;
it is skipped unless TESSLA_JAR points at the jar.
"""

import os
import shutil
import subprocess
import sys
import tempfile

from Archive.Implementations.Builders.ProcessorBuilder.PolicyConverters.TeSSLaPolicyConverter.mfotl2tessla import (
    PolicyParseError,
    UnsupportedFragmentError,
    compile_policy,
    free_vars,
    parse_policy,
)
from Archive.Implementations.Builders.ProcessorBuilder.DataConverters.TeSSLaTraceConverter.TeSSLaTraceConverter import (
    TeSSLaTraceConverter,
    TraceConversionException,
)
from Infrastructure.tests.mfotl_ref_eval import (
    RefEvaluator,
    parse_csv_trace,
    satisfied_timepoints,
)

SIG = "P0(x0:int)\nP1(x0:int)\nP2()\nP3(x0:int, x1:int)\n"

# Shapes drawn from the gen_fma fragment corpus.
CORPUS = [
    "((PREVIOUS[0,*) ((EXISTS y1. (P0(y1))))) AND ((NOT ((P2() AND (P2()))))))",
    "((PREVIOUS[0,*) ((P0(x1) SINCE[0,*) (P3(x1,x2))))) AND ((NOT ((ONCE[0,*) ((PREVIOUS[0,*) (P0(x1)))))))))",
    "((P2() SINCE[0,*) (P1(x1))) AND ((P3(x1,x2) AND ((NOT (P3(x2,x1)))))))",
    "((PREVIOUS[0,*) ((PREVIOUS[0,*) (P3(x1,x2))))) OR ((EXISTS y1. ((EXISTS y2. (((P3(x1,x2) AND ((y1 = 17))) AND ((y2 = 100)))))))))",
]

OUT_OF_FRAGMENT = [
    "(P0(x1) UNTIL[0,*) (P1(x1)))",           # unbounded future interval
    "EVENTUALLY[0,*) (P2())",                  # unbounded future interval
    "ONCE[0,*) ((EVENTUALLY[0,2] (P2())))",    # future nested under past
    "((EVENTUALLY[0,2] (P0(x1))) AND (P1(x1)))",  # future nested under AND
    "NEXT[0,*) ((NEXT[0,*) (P2())))",          # future nested under future
    "EVENTUALLY[3,1] (P0(x1))",                # negative-length interval
    "EVENTUALLY[0,0) (P0(x1))",                # empty interval
    "NEXT[0,*) ((ONCE[0,*) (P0(x1))))",        # unbounded NEXT over stateful operand
    "FORALL y1. (P0(y1))",                     # universal
    "ONCE[0,5) (P2())",                        # bounded PAST interval
    "PREVIOUS[2,*) (P2())",                    # nonzero lower bound (past)
    "NOT (P0(x1))",                            # top-level open negation (MFOTL source)
    "(P2() AND (NOT (P0(x1))))",               # unguarded open negation, nested
    "(P0(x1) OR (P3(x1,x2)))",                 # OR with differing vars
    "(x1 = x2)",                               # var = var
    "((P0(x1)) AND ((NOT (P3(x1,x2)))))",      # anti-join not covered
    "(P3(x1,x2) SINCE[0,*) (P0(x1)))",         # SINCE lhs not covered
    "(P3(x1,x2) UNTIL[0,4] (P0(x1)))",         # UNTIL lhs not covered
]


def _expect_raises(exc_type, fn, *args):
    try:
        fn(*args)
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__} from {args[:1]}")


def test_parser():
    for policy in CORPUS:
        parse_policy(policy)
    assert free_vars(parse_policy(CORPUS[1])) == ["x1", "x2"]
    _expect_raises(PolicyParseError, parse_policy, "P2() P2()")


def test_fragment_gate():
    for policy in OUT_OF_FRAGMENT:
        _expect_raises(UnsupportedFragmentError, compile_policy, policy, SIG)
    _expect_raises(
        UnsupportedFragmentError, compile_policy, "P2()", "P2()\nQ(a:string)\n"
    )


def test_codegen():
    for policy in CORPUS:
        spec = compile_policy(policy, SIG)
        assert "in mf_ts: Events[Int]" in spec
        assert "in mf_p_P0: Events[Set[List[Int]]]" in spec
        assert "out mf_v" in spec
        assert "delay(" not in spec  # generated specs are delay-free
    # Phase-1 valuation-set contract: emitted for open formulas only.
    open_spec = compile_policy(CORPUS[1], SIG)
    assert 'default(nil[String], "x1,x2")' in open_spec
    assert "out mf_setout as mf_set" in open_spec
    assert "out mf_ts" in open_spec
    closed_spec = compile_policy(CORPUS[0], SIG)
    assert "mf_set" not in closed_spec
    assert "mf_cols" not in closed_spec
    # NEGATED_MFOTL input strips the wrapper NOT and compiles the original
    # policy for satisfaction (framework negation convention, no inversion).
    negated_spec = compile_policy(f"NOT ({CORPUS[1]})", SIG, source_negated=True)
    assert "Set.size(s) > 0" in negated_spec
    assert negated_spec == compile_policy(CORPUS[1], SIG)
    # Closed top-level negation stays an ordinary MFOTL formula.
    assert "Set.size(s) > 0" in compile_policy("NOT (P2())", SIG)
    # Negative integer constants parse (trace values may be negative too).
    compile_policy("(P1(x1) AND ((x1 = -3)))", SIG)


def test_trace_converter():
    lines = [
        "P1, tp=0, ts=100, x0=5\n",
        "P2, tp=0, ts=100\n",
        "P1, tp=0, ts=100, x0=5\n",  # duplicate row collapses
        "P3, tp=1, ts=100, x0=1, x1=2\n",
        "P2, tp=3, ts=105\n",
    ]
    out = TeSSLaTraceConverter.csv_to_srv_trace(lines)
    assert out.splitlines() == [
        "0: mf_ts = 100",
        "0: mf_p_P1 = Set(List(5))",
        "0: mf_p_P2 = Set(List())",
        "1: mf_ts = 100",
        "1: mf_p_P3 = Set(List(1, 2))",
        "3: mf_ts = 105",
        "3: mf_p_P2 = Set(List())",
        "4: mf_eof = ()",  # finite-trace sentinel for future-operator flushes
    ], out
    _expect_raises(
        TraceConversionException,
        TeSSLaTraceConverter.csv_to_srv_trace,
        ["P2, tp=1, ts=1\n", "P2, tp=0, ts=0\n"],  # out of order
    )
    _expect_raises(
        TraceConversionException,
        TeSSLaTraceConverter.csv_to_srv_trace,
        ["P2, tp=0, ts=1\n", "P2, tp=0, ts=2\n"],  # conflicting timestamps
    )
    _expect_raises(
        TraceConversionException,
        TeSSLaTraceConverter.csv_to_srv_trace,
        [">WATERMARK 5<\n"],
    )
    _expect_raises(
        TraceConversionException,
        TeSSLaTraceConverter.csv_to_srv_trace,
        ["P1, tp=0, ts=0, x0=abc\n"],  # non-int value
    )
    _expect_raises(
        TraceConversionException,
        TeSSLaTraceConverter.csv_to_srv_trace,
        ["P1, tp=0, ts=0, x0=1\n", "P1, tp=1, ts=1, x0=1, x1=2\n"],  # arity drift
    )
    _expect_raises(
        TraceConversionException,
        TeSSLaTraceConverter.csv_to_srv_trace,
        ["P1, tp=0, ts=0, , x0=1\n"],  # empty argument slot
    )
    _expect_raises(
        TraceConversionException,
        TeSSLaTraceConverter.csv_to_srv_trace,
        ["P2, tp=0, ts=10\n", "P2, tp=1, ts=3\n"],  # decreasing timestamps
    )


def test_reference_evaluator():
    # EXISTS y1. (P0(y1) SINCE P1(y1)) over a hand-computed trace.
    formula = parse_policy("EXISTS y1. ((P0(y1) SINCE[0,*) (P1(y1))))")
    trace = parse_csv_trace(
        [
            "P1, tp=0, ts=100, x0=1",
            "P1, tp=0, ts=100, x0=2",
            "P0, tp=1, ts=100, x0=1",
            "P0, tp=2, ts=105, x0=1",
            "P2, tp=3, ts=106",
        ]
    )
    assert satisfied_timepoints(formula, trace) == {0, 1, 2}

    # (PREVIOUS P0(y)) SINCE P1(y): the nested register must read the
    # pre-commit PREVIOUS state (regression for update ordering).
    formula = parse_policy("((PREVIOUS[0,*) (P0(y1))) SINCE[0,*) (P1(y1)))")
    trace = parse_csv_trace(
        [
            "P1, tp=0, ts=0, x0=7",
            "P0, tp=0, ts=0, x0=7",
            "P0, tp=1, ts=1, x0=7",
            "P2, tp=2, ts=2",
        ]
    )
    rows = RefEvaluator(formula).run(trace)
    # tp0: beta holds -> {7}; tp1: PREV P0 = {7}, carried; tp2: PREV P0 = {7}
    # (P0 at tp1), carried.
    assert [bool(vals) for _, vals in rows] == [True, True, True]


def test_phase2_future():
    """Bounded-future roots: codegen contract, reference semantics, and (if
    available) wrapper parsing of tagged late verdicts."""
    from Archive.Implementations.Builders.ProcessorBuilder.PolicyConverters.TeSSLaPolicyConverter.mfotl2tessla import (
        Eventually, Interval,
    )

    spec = compile_policy("EVENTUALLY[0,2] (P0(x1))", SIG)
    assert "in mf_eof: Events[Unit]" in spec
    assert "out filter(mf_frf, mf_haslate) as mf_late_set" in spec
    assert "mf_fr_flush" in spec  # finite-trace flush at end of trace
    assert "mf_v" not in spec  # future roots have no synchronous verdict
    closed_spec = compile_policy("EVENTUALLY[0,4] (P0(9))", SIG)
    assert "mf_cols" not in closed_spec
    until_spec = compile_policy("((NOT (P0(x1))) UNTIL[0,4) (P1(x1)))", SIG)
    assert "mf_late_set" in until_spec

    # Interval exclusivity is preserved by the parser.
    formula = parse_policy("EVENTUALLY[1,3) (P0(x1))")
    assert isinstance(formula, Eventually)
    assert isinstance(formula.interval, Interval)
    assert formula.interval.high == 3 and formula.interval.high_exclusive

    # Reference finite-trace semantics, hand-computed:
    # trace tps 0..2, ts 100/101/105; EVENTUALLY[0,2] P1(x1).
    from Infrastructure.tests.mfotl_ref_eval import evaluate_policy
    trace = parse_csv_trace(
        [
            "P0, tp=0, ts=100, x0=7",
            "P1, tp=1, ts=101, x0=5",
            "P1, tp=2, ts=105, x0=6",
        ]
    )
    rows, closed = evaluate_policy(parse_policy("EVENTUALLY[0,2] (P1(x1))"), trace)
    by_tp = {tp: {dict(v)["x1"] for v in vals} for tp, vals in rows}
    # tp0 [100,102]: P1@101 -> {5}; tp1 [101,103]: {5}; tp2 [105,107]: {6}
    # (tp2's window is open at end of trace; finite-trace still counts j=2).
    assert by_tp == {0: {5}, 1: {5}, 2: {6}}, by_tp
    assert closed == {0, 1, 2}

    # MonPoly's virtual empty timepoint at timestamp infinity: an
    # upper-unbounded NEXT over carried state IS satisfied at the last
    # timepoint (the compiler rejects this family; the reference models it).
    rows, _ = evaluate_policy(
        parse_policy("NEXT[0,*) ((ONCE[0,*) (P1(x1))))"), trace
    )
    virtual = {tp: {dict(v)["x1"] for v in vals} for tp, vals in rows}
    assert virtual == {0: {5}, 1: {5, 6}, 2: {5, 6}}, virtual

    try:
        from Archive.Implementations.Monitors.TeSSLa.TeSSLa import TeSSLa
    except ImportError as e:
        print(f"  (wrapper part skipped: {e})")
        return
    from Infrastructure.DataTypes.Verification.OutputStructures.Structures.OooVerdicts import OooVerdicts

    wrapper = object.__new__(TeSSLa)
    stdout = "\n".join([
        "0: mf_cols = x1",
        "0: mf_ts = 100",
        "1: mf_ts = 101",
        "2: mf_late_set = Set(List(0, 5), List(1, 5))",
        "2: mf_ts = 105",
        "3: mf_late_set = HashSet(List(2, 6))",
    ])
    tool = wrapper.post_processing_offline(stdout)
    assert isinstance(tool, OooVerdicts), type(tool)
    assert set(tool.time_points().keys()) == {0, 1, 2}
    assert tool.time_points()[0] == 100
    values_tp0 = [a.values for a in tool.retrieve(0)[2]]
    assert values_tp0 == [["5"]], values_tp0
    # Closed future roots re-key into a PropositionList.
    closed_tool = wrapper.post_processing_offline("5: mf_late_set = Set(List(3))")
    assert set(closed_tool.time_points().keys()) == {3}


def test_phase1_verdict_parsing():
    """Wrapper builds Verdicts from the phase-1 contract and the framework
    comparator accepts them against an oracle in a DIFFERENT variable order.
    Needs the framework's docker dependency chain; run under the repo venv."""
    try:
        from Archive.Implementations.Monitors.TeSSLa.TeSSLa import TeSSLa
    except ImportError as e:
        print(f"  (skipped: framework import unavailable: {e})")
        return
    from Archive.Implementations.Monitors.SharedFunctions import parse_monpoly_output
    from Infrastructure.DataTypes.Verification.OutputStructures.Structures.Verdicts import Verdicts
    from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.VariableOrder import VariableOrder
    from Infrastructure.Monitors.MonitorExceptions import ToolException

    wrapper = object.__new__(TeSSLa)
    stdout = "\n".join([
        "0: mf_cols = x1,x2",
        "3: mf_ts = 100",
        "3: mf_set = Set(List(1, 2), List(3, 4))",
        "3: mf_v = true",
        "5: mf_ts = 101",
        "5: mf_v = false",
        "7: mf_ts = 105",
        "7: mf_set = HashSet(List(1, 2))",  # JVM prints large sets this way
        "7: mf_v = true",
    ])
    tool = wrapper.post_processing_offline(stdout)
    assert isinstance(tool, Verdicts), type(tool)
    assert tool.retrieve_order() == ["x1", "x2"]
    assert set(tool.time_points().keys()) == {3, 7}
    assert tool.time_points()[3] == 100

    # Oracle in MonPoly's own (different) variable order, same valuations.
    oracle = parse_monpoly_output(
        Verdicts(VariableOrder(["x2", "x1"])),
        "@100 (time point 3): (2,1) (4,3)\n@105 (time point 7): (2,1)\n",
    )
    ok, message = oracle.as_oracle(tool)
    assert ok, message

    # A value-level difference must be caught (presence alone matches here).
    wrong = wrapper.post_processing_offline(stdout.replace("List(3, 4)", "List(3, 5)"))
    ok, message = oracle.as_oracle(wrong)
    assert not ok, "comparator must reject differing valuations"

    # Runtime errors still raise, and phase-0 output still degrades cleanly.
    try:
        wrapper.post_processing_offline("Runtime error: boom")
        raise AssertionError("expected ToolException")
    except ToolException:
        pass
    fallback = wrapper.post_processing_offline("2: mf_v = true\n3: mf_v = false")
    assert set(fallback.time_points().keys()) == {2}


def test_end_to_end():
    jar = os.environ.get("TESSLA_JAR")
    if not jar or shutil.which("java") is None:
        print("  (skipped: set TESSLA_JAR to the tessla assembly jar)")
        return
    policy = "EXISTS y1. ((P0(y1) SINCE[0,*) (P1(y1))))"
    csv = [
        "P1, tp=0, ts=100, x0=1\n",
        "P1, tp=0, ts=100, x0=2\n",
        "P0, tp=1, ts=100, x0=1\n",
        "P0, tp=2, ts=105, x0=1\n",
        "P2, tp=3, ts=106\n",
    ]
    spec = compile_policy(policy, SIG)
    srv = TeSSLaTraceConverter.csv_to_srv_trace(csv)
    with tempfile.TemporaryDirectory() as tmp:
        spec_path = os.path.join(tmp, "spec.tessla")
        trace_path = os.path.join(tmp, "trace.input")
        with open(spec_path, "w") as f:
            f.write(spec)
        with open(trace_path, "w") as f:
            f.write(srv)
        proc = subprocess.run(
            [
                "java", "-Xss512m", "-jar", jar,
                "interpreter", "--reject-undeclared-inputs",
                spec_path, trace_path,
            ],
            capture_output=True, text=True, timeout=120,
        )
    assert proc.returncode == 0, proc.stderr
    assert "Runtime error" not in proc.stderr, proc.stderr
    verdicts = [line for line in proc.stdout.splitlines() if ": mf_v = " in line]
    assert verdicts == [
        "0: mf_v = true",
        "1: mf_v = true",
        "2: mf_v = true",
        "3: mf_v = false",
    ], verdicts


def main():
    tests = [
        test_parser,
        test_fragment_gate,
        test_codegen,
        test_trace_converter,
        test_reference_evaluator,
        test_phase1_verdict_parsing,
        test_phase2_future,
        test_end_to_end,
    ]
    for test in tests:
        print(f"{test.__name__} ...")
        test()
        print(f"{test.__name__} OK")
    print(f"\nAll {len(tests)} test groups passed.")


if __name__ == "__main__":
    main()
