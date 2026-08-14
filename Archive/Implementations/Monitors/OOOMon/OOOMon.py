import re
from typing import Dict, AnyStr, Any, Tuple, List, Optional

from Infrastructure.AutoConversion.InputOutputPolicyFormats import InputOutputPolicyFormats
from Infrastructure.AutoConversion.InputOutputTraceFormats import InputOutputTraceFormats
from Infrastructure.Builders.ToolBuilder.ToolImageManager import AbstractToolImageManager
from Infrastructure.DataTypes.PathManager.PathManager import PathManager
from Infrastructure.DataTypes.Verification.OutputStructures.AbstractOutputStrucutre import AbstractOutputStructure
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.OooVerdicts import OooVerdicts
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.VariableOrder import VariableOrder, \
    DefaultVariableOrder
from Infrastructure.Monitors.BaseMonitorTemplate import BaseMonitorTemplate, OfflineRunnable
from Infrastructure.constants import POLICY_KEY, TRACE_KEY, SIGNATURE_KEY, FOLDER_KEY


class OOOMon(BaseMonitorTemplate, OfflineRunnable):
    """The Isabelle-verified out-of-order reference monitor (formalized_streaming_monitor).

    Everything between a parsed token and a printed verdict runs OCaml code
    exported from the verified OOOMonitor session; only the parsers and
    printers are unverified glue.  Policies are fragment-direct s-expressions
    (format "ooo-fragment"); traces are the TimelyMon CSV wire format,
    in-order or out-of-order, with optional time-point watermarks.
    """

    def __init__(self, image: AbstractToolImageManager, name, params: Dict[AnyStr, Any]):
        super().__init__(image, name, params)

    def preprocessing_data(
            self, path_to_folder: AnyStr, data_file: AnyStr,
            trace_source: InputOutputTraceFormats, path_manager: PathManager
    ):
        raise NotImplementedError("OOOMon does not support non-automatic preprocessing for data")

    def preprocessing_policy(self, path_to_folder: AnyStr, policy_file: AnyStr, signature_file: AnyStr,
                             policy_source: InputOutputPolicyFormats, path_manager: PathManager):
        raise NotImplementedError("OOOMon does not support non-automatic preprocessing for policies")

    def construct_offline_command(self) -> Tuple[List[str], Optional[str]]:
        cmd = ["-formula", str(self.params[POLICY_KEY]),
               "-log", str(self.params[TRACE_KEY]),
               "-format", "timelymon"]
        if not self.params.get("ignore_signature", False):
            cmd += ["-sig", str(self.params[SIGNATURE_KEY])]
        if self.params.get("no_claims", False):
            cmd += ["-no-claims"]
        return cmd, None

    def post_processing_offline(self, stdout_input: AnyStr) -> AbstractOutputStructure:
        variable_order = self._variable_order()
        return parse_output_structure(stdout_input, variable_order)

    def _variable_order(self):
        cmd = ["-formula", str(self.params[POLICY_KEY]), "-columns"]
        logs, code = self.image.run_offline(self.params[FOLDER_KEY], cmd, measure=False)
        order = parse_variable_order_ooomon(logs) if code == 0 else []
        return VariableOrder(order) if order else DefaultVariableOrder()

    @staticmethod
    def supported_policy_formats() -> List[InputOutputPolicyFormats]:
        return [InputOutputPolicyFormats.OOO_FRAGMENT]

    @staticmethod
    def supported_trace_formats() -> List[InputOutputTraceFormats]:
        return [InputOutputTraceFormats.CSV, InputOutputTraceFormats.OOO_CSV]


def parse_variable_order_ooomon(text: AnyStr) -> List[str]:
    """`ooomon -formula F -columns` prints exactly one line: `# columns: x0 x1 ...`."""
    match = re.search(r"#\s*columns:\s*(.*)", text)
    if not match:
        return []
    return [v for v in match.group(1).split() if v]


def parse_output_structure(input_val: AnyStr, variable_ordering) -> AbstractOutputStructure:
    """Parse `@tp (v1,v2,...)` verdict lines; `# columns` headers and
    `!complete` claims are metadata, not verdicts."""
    verdicts = OooVerdicts(variable_order=variable_ordering)
    if input_val is None or input_val.strip() == "":
        return verdicts

    line_pattern = re.compile(r'^@(\d+)\s*\((.*)\)\s*$')
    for line in input_val.strip().split("\n"):
        line = line.strip()
        if not line.startswith("@"):
            continue
        match = line_pattern.match(line)
        if not match:
            continue
        tp = int(match.group(1))
        raw = match.group(2)
        values = [_strip_quotes(v) for v in _split_top_level(raw)]
        verdicts.insert([values] if values else [[]], tp, None)
    return verdicts


def _split_top_level(s: str) -> List[str]:
    """Split a verdict tuple on commas, respecting double-quoted strings."""
    out, buf, in_q = [], [], False
    for c in s:
        if c == '"':
            in_q = not in_q
            buf.append(c)
        elif c == ',' and not in_q:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
    tail = "".join(buf).strip()
    if tail or out:
        out.append(tail)
    return [v for v in out if v != ""]


def _strip_quotes(v: str) -> str:
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1]
    return v
