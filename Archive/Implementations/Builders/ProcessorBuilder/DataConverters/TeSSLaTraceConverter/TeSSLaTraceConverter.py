import re
from typing import Any, AnyStr, Dict, List, Tuple

from Infrastructure.AutoConversion.InputOutputTraceFormats import InputOutputTraceFormats
from Infrastructure.Builders.ProcessorBuilder.DataConverters.DataConverterTemplate import DataConverterTemplate


class TraceConversionException(Exception):
    pass


_ROW_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*tp\s*=\s*(\d+)\s*,\s*ts\s*=\s*(\d+)\s*(.*)$"
)
_ARG_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*=\s*(-?\d+)")


class TeSSLaTraceConverter(DataConverterTemplate):
    """In-process CSV -> TeSSLa trace (srv-trace) converter, phase 0.

    Encoding contract (shared with TeSSLaPolicyConverter): TeSSLa time is the
    timepoint index; ``mf_ts`` ticks at every timepoint carrying the original
    timestamp; each predicate P with events at a timepoint yields exactly one
    event ``tp: mf_p_P = Set(List(args), ...)``.  Duplicate rows collapse
    (relations are sets).  Deliberately signature-free: the trace chain runs
    before the signature lands in params, and rows carry predicate and arity.

    Rejects out-of-order timepoints and watermark/command rows; route OOO_CSV
    through OutOfOrderConverter (OOO_CSV -> CSV) first, which the BFS
    conversion router does automatically.
    """

    def __init__(self, name, path_to_project):
        pass

    def convert(self, path_to_folder: AnyStr, data_file: AnyStr, tool: AnyStr, name: AnyStr, dest: AnyStr, params):
        raise TraceConversionException(
            "TeSSLaTraceConverter only supports the auto-conversion path"
        )

    def auto_convert(self, path_to_folder: str, input_file: str, path_to_output_folder: str, output_file: str,
                     source: InputOutputTraceFormats, target: InputOutputTraceFormats, params: Dict[str, Any]):
        if (source, target) not in self.conversion_scheme():
            raise TraceConversionException(
                f"Incompatible conversion from {source} to {target}"
            )
        with open(f"{path_to_folder}/{input_file}", "r") as trace_file:
            lines = trace_file.readlines()
        converted = self.csv_to_srv_trace(lines)
        with open(f"{path_to_output_folder}/{output_file}", "w") as out:
            out.write(converted)

    @staticmethod
    def csv_to_srv_trace(lines: List[str]) -> str:
        # timepoints in encounter order: [(tp, ts, {pred: set of arg tuples})]
        timepoints: List[Tuple[int, int, Dict[str, set]]] = []
        arities: Dict[str, int] = {}
        current_tp = None
        for line_number, raw in enumerate(lines, start=1):
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                raise TraceConversionException(
                    f"Line {line_number}: command/watermark rows ({line[:30]!r}) "
                    f"are not supported; TeSSLa requires an in-order trace"
                )
            match = _ROW_RE.match(line)
            if not match:
                raise TraceConversionException(
                    f"Line {line_number}: cannot parse CSV row {line[:60]!r}"
                )
            predicate, tp, ts = match.group(1), int(match.group(2)), int(match.group(3))
            rest = match.group(4).strip()
            if rest and not rest.startswith(","):
                raise TraceConversionException(
                    f"Line {line_number}: unexpected trailing content {rest[:40]!r}"
                )
            values = []
            if rest:
                for chunk in rest.lstrip(",").split(","):
                    arg_match = _ARG_RE.fullmatch(chunk.strip())
                    if not arg_match:
                        raise TraceConversionException(
                            f"Line {line_number}: cannot parse argument "
                            f"{chunk.strip()!r} (phase 0 supports integer values "
                            f"only; empty argument slots are rejected)"
                        )
                    values.append(int(arg_match.group(1)))
            if arities.setdefault(predicate, len(values)) != len(values):
                raise TraceConversionException(
                    f"Line {line_number}: predicate {predicate} carries "
                    f"{len(values)} arguments here but {arities[predicate]} "
                    f"earlier; inconsistent arity would silently corrupt verdicts"
                )

            if current_tp is None or tp != current_tp:
                # tp is non-decreasing, so current_tp is the running maximum
                # and a reopened timepoint is impossible once this holds.
                if current_tp is not None and tp < current_tp:
                    raise TraceConversionException(
                        f"Line {line_number}: timepoint {tp} after {current_tp}; "
                        f"out-of-order traces must be converted to CSV first"
                    )
                if timepoints and ts < timepoints[-1][1]:
                    raise TraceConversionException(
                        f"Line {line_number}: timestamp {ts} at timepoint {tp} "
                        f"is smaller than {timepoints[-1][1]} at the previous "
                        f"timepoint; MFOTL traces are timestamp-monotone"
                    )
                timepoints.append((tp, ts, {}))
                current_tp = tp
            entry = timepoints[-1]
            if entry[1] != ts:
                raise TraceConversionException(
                    f"Line {line_number}: timepoint {tp} carries timestamps "
                    f"{entry[1]} and {ts}"
                )
            entry[2].setdefault(predicate, set()).add(tuple(values))

        out_lines = []
        for tp, ts, relations in timepoints:
            out_lines.append(f"{tp}: mf_ts = {ts}")
            for predicate in sorted(relations):
                tuples = sorted(relations[predicate])
                rendered = ", ".join(
                    "List(" + ", ".join(str(v) for v in row) + ")" for row in tuples
                )
                out_lines.append(f"{tp}: mf_p_{predicate} = Set({rendered})")
        if timepoints:
            # End-of-trace sentinel, one tick after the last timepoint (a time
            # with no mf_ts event, so timepoint-synchronous streams stay
            # silent).  Bounded-future registers flush their residual owed
            # verdicts on it, matching MonPoly's finite-trace semantics at the
            # end of the log.
            out_lines.append(f"{timepoints[-1][0] + 1}: mf_eof = ()")
        return "\n".join(out_lines) + ("\n" if out_lines else "")

    @staticmethod
    def conversion_scheme() -> List[Tuple[InputOutputTraceFormats, InputOutputTraceFormats]]:
        return [
            (InputOutputTraceFormats.CSV, InputOutputTraceFormats.SRV_TRACE),
        ]
