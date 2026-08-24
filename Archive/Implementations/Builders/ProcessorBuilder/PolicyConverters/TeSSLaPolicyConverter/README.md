# TeSSLaPolicyConverter (phases 0-2: past fragment, valuation verdicts, bounded-future roots)

In-process compiler from MonPoly-syntax MFOTL to a self-contained TeSSLa
specification (`srv-policy`), making TeSSLa reachable from the MFOTL
benchmarks via the automatic conversion router. Companion pieces:

- `DataConverters/TeSSLaTraceConverter` — CSV -> `srv-trace` (the encoding's
  other half; OOO_CSV routes through OutOfOrderConverter automatically)
- `Monitors/TeSSLa` — passes `--reject-undeclared-inputs`, scans the captured
  output for `Runtime error:` (the interpreter exits 0 on runtime-phase
  errors, including trace-format violations), and parses `mf_v` verdict lines
  into a `PropositionList`
- `Infrastructure/tests/test_tessla_converter.py` — unit + end-to-end tests
- `Infrastructure/tests/mfotl_ref_eval.py` — independent reference evaluator
  used as a second oracle in differential validation

## Encoding

| MFOTL | TeSSLa |
|---|---|
| timepoint index `i` | the time axis (one tick per timepoint) |
| timestamp `ts_i` | data value on input stream `mf_ts` |
| database relation of predicate `P` at `i` | one event `i: mf_p_P = Set(List(args), ...)` (absent = empty, restored via `merge`) |
| subformula | one `Events[Set[List[Int]]]` stream, columns = sorted free variables |
| temporal operators | `last`-based registers (delay-free) |
| verdict (boolean) | `out mf_v: Events[Bool]`, true iff the existential closure holds |
| verdict (valuations, open formulas) | `mf_cols` (column order, one string event at time 0), `mf_ts` echo, `mf_set` = the satisfying valuation set, emitted exactly at satisfying timepoints |

The wrapper turns the valuation contract into a `Verdicts` structure (values
kept as strings, matching `parse_pattern`'s convention), so the framework
compares TeSSLa against the MonPoly-family oracle value by value; `Assignment`
equality is variable-name-based, so the sorted column order compares correctly
against the oracle's own order. Closed formulas and native srv case-study
specs fall back to the propositional `PropositionList` path. Note: phase 1
also fixed `Verdicts.retrieve` (it matched on the timestamp instead of the
timepoint, silently skipping value-level comparison whenever ts != tp).

Duplicate timestamps across timepoints, empty databases, and multi-tuple
relations are all representable; the generated specification stays in the
delay-free (timestamp-conservative) TeSSLa fragment.

## Supported fragment (hard error outside it)

Past-only MFOTL with intervals exactly `[0,*)`: predicates over `int`
columns, `AND` / `OR` (equal free variables) / guarded or closed `NOT` /
`EXISTS` / `var = const`, `PREVIOUS[0,*)`, `ONCE[0,*)`, `SINCE[0,*)` (also
with negated left-hand side), under MonPoly-style safety. A top-level
`NOT (...)` is treated as the NEGATED_MFOTL convention: the inner formula's
closure is monitored and the boolean verdict inverted.

Phase 2 adds ONE bounded-future operator at the root, optionally under
existential quantifiers, over past-only operands: `NEXT_I` (any interval),
`EVENTUALLY_I` and `UNTIL_I` (finite upper bound; also with a negated
left-hand side). Verdicts for timepoint i become known later; the generated
spec keeps an owed-obligation register and emits them at the closing
timepoint as tagged tuples on `mf_late_set` (elements `List(tp, cols...)`),
plus a finite-trace flush on the `mf_eof` sentinel that the trace converter
appends one tick after the last timepoint, matching MonPoly's semantics at
the end of an offline log. The wrapper re-keys tagged verdicts by timepoint
into `OooVerdicts` (open roots) or a `PropositionList` (closed roots).
Future operators anywhere below the root are a hard error: that would need
per-operator out-of-order buffering (TimelyMon's problem) and stays out of
scope. Two further gates mirror the MonPoly oracle exactly: negative or
empty intervals are rejected (MonPoly's check_wff does too, where we would
otherwise compile a silently never-true monitor), and upper-unbounded NEXT
is allowed only over operands that are empty on an empty database, because
MonPoly evaluates the last timepoint's NEXT against a virtual empty
timepoint at timestamp infinity (probed empirically; the reference
evaluator models that virtual timepoint exactly). Note for hand-written
srv setups: converter traces end with the mf_eof sentinel, so a native spec
run with reject_undeclared: True on a converter trace will error at the
sentinel; native specs should either declare mf_eof or not opt into -r.

Not yet: bounded/lower-bounded PAST intervals, future operators nested under
other operators, aggregations, MFODL regex, `let`/`rec`, string data (TeSSLa
prints strings unquoted, so string verdicts cannot be re-parsed reliably).

Polarity is keyed on the SOURCE FORMAT, not on syntax: NEGATED_MFOTL input
(`NOT (phi)` from the negation plumbing) strips the wrapper and monitors phi
for satisfaction, so verdicts line up with the satisfaction oracle exactly
as in the DejaVu chain; a plain-MFOTL policy whose top level is `NOT` over
an open formula is rejected, matching MonPoly's monitorability check.

## Operational notes

- The interpreter's lazy evaluation recurses proportionally to Set sizes and
  overflows the default JVM stack on converted MFOTL relations; the tool
  Dockerfile passes `-Xss1g` for that reason (512m still overflowed on the
  `num_2` fragment policy at 100 timepoints; 1g completes it in ~13min).
  Run local experiments the same way. The real fix is the `compile-rust`
  backend: the same generated spec compiled to a native monitor
  (`tessla compile-rust -b m spec.tessla`, needs cargo) runs that case in
  ~6s (data_500 in ~2.5min) with verdicts exactly matching VeriMon; wiring
  it in as an `offline_compile` step (DejaVu precedent) is the planned
  phase-2 performance lane.
- Large sets print as `HashSet(...)`, not `Set(...)`; relevant only when
  parsing set-valued debug output (`compile_policy(..., debug_set_output=True)`
  emits `out ... as mf_set`), not for `mf_v`.
- The signature reaches `auto_convert` through `params[SIGNATURE_KEY]` /
  `params[FOLDER_KEY]`; the trace converter is deliberately signature-free
  because the trace chain runs before those params are set. It instead
  enforces per-predicate arity consistency, timestamp monotonicity, and
  strict argument parsing, and the generated spec carries a `List.size`
  guard per atom, so malformed rows in hand-written srv traces are dropped
  (mirroring the reference evaluator) rather than silently satisfying
  quantifiers.
- Temporal registers anchor "no previous timepoint" with
  `merge(last(...), mf_tick)`, never `default(...)`: `default` would place a
  phantom event at TeSSLa time 0, which is wrong for traces whose first
  timepoint is not 0.
- Timepoint labels pass through verbatim; like the rest of the framework,
  cross-tool comparison assumes traces number their timepoints densely from
  0 (MonPoly-format oracles renumber by position).

## Validation (2026-08-24)

Differential sweep over the ten `tool_comparison_synthetic_experiment_fragment`
policies, trace sizes 10/50/100/500: TeSSLa 2.1.0 verdicts agree exactly, on
timepoint sets and full valuation sets, with the stored VeriMon results and
with the independent reference evaluator (38/38 completed runs; two runs hit
the interpreter throughput ceiling and timed out, no disagreement). A
21-case micro-suite covers the paths the corpus misses (constant arguments,
repeated variables, equality forms, negated/closed SINCE left-hand sides,
projections, vacuous quantifiers, negated top-level).
