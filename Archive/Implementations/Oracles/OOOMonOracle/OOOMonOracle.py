import ast
import copy
from typing import AnyStr, Tuple

from Infrastructure.AutoConversion.InputOutputPolicyFormats import InputOutputPolicyFormats
from Infrastructure.AutoConversion.InputOutputTraceFormats import InputOutputTraceFormats
from Infrastructure.DataTypes.PathManager.PathManager import PathManager
from Infrastructure.DataTypes.Verification.OutputStructures.AbstractOutputStrucutre import AbstractOutputStructure
from Infrastructure.DataTypes.Verification.OutputStructures.Compare.Comparing import comparing
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.VariableOrder import VariableOrder, \
    DefaultVariableOrder
from Infrastructure.Monitors.BaseMonitorTemplate import BaseMonitorTemplate
from Infrastructure.Oracles.AbstractOracleTemplate import AbstractOracleTemplate
from Infrastructure.constants import SIGNATURE_KEY, POLICY_KEY, FOLDER_KEY, TRACE_KEY
from Archive.Implementations.Monitors.OOOMon.OOOMon import parse_output_structure, parse_variable_order_ooomon


class OOOMonOracle(AbstractOracleTemplate):
    """The verified reference monitor as an oracle.

    Wraps an OOOMon monitor instance and replays the experiment's policy and
    trace through the Isabelle-exported core; the emitted verdict set is the
    specification's verdict set (monitor_correct_build), so a tool agrees with
    the semantics iff it agrees with this oracle.  Under the out-of-order
    contract the oracle is sound and, since the diagonal repair, complete on
    every semantically determined time-point.
    """

    def __init__(self, ooo_mon: BaseMonitorTemplate, parameters):
        super().__init__(None, None)
        self.ooomon = copy.deepcopy(ooo_mon)
        self.ooomon.name = "OOOMon"
        self.parameters = parameters

    def pre_process_data(
            self, path_to_folder: str, trace_source_format: InputOutputTraceFormats,
            policy_source_format: InputOutputPolicyFormats, data_file: str, signature_file: str, policy_file: str,
            path_manager: PathManager
    ):
        self.ooomon.preprocessing(
            path_to_folder, trace_source_format, policy_source_format, data_file, signature_file, policy_file,
            path_manager
        )

    def compute_result(self, time_on=None, time_out=None) -> Tuple[AnyStr, int]:
        cmd = ["-formula", str(self.ooomon.params[POLICY_KEY]),
               "-log", str(self.ooomon.params[TRACE_KEY]),
               "-format", "timelymon",
               "-sig", str(self.ooomon.params[SIGNATURE_KEY])]
        return self.ooomon.image.run_offline(self.ooomon.params[FOLDER_KEY], cmd, time_on, time_out)

    def post_process_data(self, std_out_str, output_file_name):
        cmd = ["-formula", str(self.ooomon.params[POLICY_KEY]), "-columns"]
        logs, code = self.ooomon.image.run_offline(self.ooomon.params[FOLDER_KEY], cmd, measure=False)
        if code != 0:
            raise Exception(f"Error in post-processing OOOMon output variable order: {logs}")

        variable_order = parse_variable_order_ooomon(logs)
        with open(f"{output_file_name}.vo", "w") as file:
            file.write(str(variable_order))
        with open(output_file_name, "w") as file:
            file.write(std_out_str)

    def verify(self, path_to_result_folder: AnyStr, data_file: AnyStr, tool_verdicts: AbstractOutputStructure,
               sig_file, formula_file, result_file) -> Tuple[bool, AnyStr]:
        oracle_verdicts = get_oracle_verdicts(result_file)
        return comparing(oracle_verdicts, tool_verdicts)


def get_oracle_verdicts(result_file) -> AbstractOutputStructure:
    with open(f"{result_file}.vo", "r") as file:
        raw_vo = file.read()
    variable_order = VariableOrder(ast.literal_eval(raw_vo)) if raw_vo.strip() else DefaultVariableOrder()

    with open(result_file, "r") as file:
        stdout_input = file.read()

    return parse_output_structure(stdout_input, variable_order)
