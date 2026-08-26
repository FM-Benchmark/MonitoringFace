import hashlib
import os
from typing import Dict, AnyStr, Any, Tuple, List, Optional

from Infrastructure.AutoConversion.InputOutputPolicyFormats import InputOutputPolicyFormats
from Infrastructure.AutoConversion.InputOutputTraceFormats import InputOutputTraceFormats
from Infrastructure.Builders.ToolBuilder.ToolImageManager import AbstractToolImageManager
from Infrastructure.DataTypes.PathManager.PathManager import PathManager
from Infrastructure.DataTypes.Verification.OutputStructures.AbstractOutputStrucutre import AbstractOutputStructure
from Infrastructure.DataTypes.Verification.OutputStructures.Structures.Verdicts import Verdicts
from Infrastructure.DataTypes.Verification.OutputStructures.SubTypes.VariableOrder import VariableOrder, DefaultVariableOrder
from Infrastructure.Monitors.BaseMonitorTemplate import BaseMonitorTemplate, OfflineRunnable
from Infrastructure.Monitors.MonitorExceptions import ToolException
from Archive.Implementations.Monitors.SharedFunctions import parse_variable_order_monpoly, parse_monpoly_output
from Infrastructure.constants import SIGNATURE_KEY, POLICY_KEY, TRACE_KEY, FOLDER_KEY


class StaticMon(BaseMonitorTemplate, OfflineRunnable):
    """StaticMon compiles a specialized monitor binary per (signature, formula)
    pair -- like DejaVu -- but speaks MonPoly's languages: MFOTL policies,
    MonPoly log traces and MonPoly-format verdicts."""

    def __init__(self, image: AbstractToolImageManager, name, params: Dict[AnyStr, Any]):
        super().__init__(image, name, params)
        self._compile_logs = ""

    def preprocessing_data(
            self, path_to_folder: AnyStr, data_file: AnyStr,
            trace_source: InputOutputTraceFormats, path_manager: PathManager
    ):
        raise NotImplementedError("StaticMon does not support non-automatic preprocessing for data")

    def preprocessing_policy(
            self, path_to_folder: AnyStr, policy_file: AnyStr, signature_file: AnyStr,
            policy_source: InputOutputPolicyFormats, path_manager: PathManager
    ):
        raise NotImplementedError("StaticMon does not support non-automatic preprocessing for policies")

    def _monitor_binary(self) -> str:
        # The compiled monitor lands in the shared scratch folder under a name
        # derived from the signature+policy contents (DejaVu's scheme), so
        # concurrent settings in one experiment folder cannot collide.
        digest = hashlib.md5()
        for key in (SIGNATURE_KEY, POLICY_KEY):
            with open(f"{self.params[FOLDER_KEY]}/{self.params[key]}", "rb") as f:
                digest.update(f.read())
        return f"scratch/staticmon-{digest.hexdigest()}.bin"

    def offline_compile(self):
        os.makedirs(f"{self.params[FOLDER_KEY]}/scratch", exist_ok=True)
        # -verbose makes the compile emit MonPoly's "The sequence of free
        # variables is: (...)" header, which post-processing reuses; the kept
        # binary is what `staticmon run` executes in the next container.
        # -cache puts staticmon's binary cache in the mounted experiment
        # folder, so a formula compiles once (per tool version: the cache is
        # namespaced by staticmon's build fingerprint) and later compiles are
        # near-instant hits. It must live OUTSIDE scratch/: the harness's
        # ScratchFolderHandler wipes scratch after every (setting, size)
        # iteration, which would kill the cache between data sizes.
        cmd = [
            "compile",
            "-sig", str(self.params[SIGNATURE_KEY]),
            "-formula", str(self.params[POLICY_KEY]),
            "-cache", "staticmon-cache",
            "-keep", self._monitor_binary(),
            "-verbose",
        ]
        out, code = self.image.run_offline(self.params[FOLDER_KEY], cmd, measure=False)
        if code != 0:
            raise ToolException(f"StaticMon compilation failed with code {code} and output: {out}")
        self._compile_logs = out

    def construct_offline_command(self) -> Tuple[List[str], Optional[str]]:
        return ["run", "-monitor", self._monitor_binary(), "-log", str(self.params[TRACE_KEY])], None

    def post_processing_offline(self, stdout_input: AnyStr) -> AbstractOutputStructure:
        order = parse_variable_order_monpoly(self._compile_logs)
        variable_order = VariableOrder(order) if order else DefaultVariableOrder()
        return parse_monpoly_output(Verdicts(variable_order=variable_order), stdout_input)

    @staticmethod
    def supported_policy_formats() -> List[InputOutputPolicyFormats]:
        return [InputOutputPolicyFormats.MFOTL]

    @staticmethod
    def supported_trace_formats() -> List[InputOutputTraceFormats]:
        return [InputOutputTraceFormats.MONPOLY, InputOutputTraceFormats.MONPOLY_LINEAR]
