import subprocess
from typing import AnyStr, List, Tuple, Dict, Any

from Infrastructure.Builders.ProcessorBuilder.DataConverters.DataConverterTemplate import DataConverterTemplate
from Infrastructure.Builders.ProcessorBuilder.ImageManager import Processor, ImageManager
from Infrastructure.AutoConversion.InputOutputTraceFormats import InputOutputTraceFormats, trace_inout_format_to_str
from Infrastructure.Monitors.MonitorExceptions import ReplayerException
from Infrastructure.constants import POLICY_CONSTANTS_APPLIED, POLICY_CONSTANTS_FILE

# The trace itself arrives on stdin, so the container has no mount of its own; the
# constants file the policy conversion left in the scratch folder needs one.
INIT_MOUNT = "/init"


class ReplayerConverter(DataConverterTemplate):
    def __init__(self, name, path_to_project):
        self.image = ImageManager(name, Processor.DataConverters, path_to_project)

    def auto_convert(
        self, path_to_folder: str, input_file: str,
        path_to_output_folder: str, output_file: str,
        source: InputOutputTraceFormats, target: InputOutputTraceFormats, params: Dict[str, Any]
    ):
        cmd_params = params["cmd_params"] if "cmd_params" in params else ["-a", "0"]
        cast_source = trace_inout_format_to_str(source)
        cast_target = trace_inout_format_to_str(target)

        constants_file = None if params.get(POLICY_CONSTANTS_APPLIED) else params.get(POLICY_CONSTANTS_FILE)
        mount, init = [], []
        if constants_file:
            if target == InputOutputTraceFormats.DEJAVU:
                raise ReplayerException(
                    f"cannot register the policy's constants ({constants_file}) in a "
                    f"{cast_target} trace: the format admits a single event per time point "
                    f"and the trace's first one is already taken; convert to "
                    f"dejavu-encoded or dejavu-linear instead"
                )
            mount = ["-v", f"{path_to_folder}:{INIT_MOUNT}:ro"]
            init = ["-init", f"{INIT_MOUNT}/{constants_file}"]

        command = ["docker", "run", "--rm", "--entrypoint", "java", "-i"] + mount + [
                   f"{self.image.image_name.lower()}", "-cp", "classes:libs/*",
                   "org.entry.Dispatcher", "Replayer", "-i", f"{cast_source}", "-f", f"{cast_target}"] + init + cmd_params

        with open(f"{path_to_folder}/{input_file}", 'r') as input_file:
            result = subprocess.run(command, stdin=input_file, capture_output=True, text=True)
            if result.returncode == 0:
                with open(f"{path_to_output_folder}/{output_file}", "w") as f:
                    for line in filter(lambda x: not x.startswith(">W"), result.stdout.splitlines()):
                        f.write(line + "\n")
            else:
                print(f"Error: {result.stderr}")
                raise ReplayerException(f"Replayer Failed {result.stderr}")
        if constants_file:
            params[POLICY_CONSTANTS_APPLIED] = True
        return command  # exact argv, recorded in the provenance manifest

    def convert(
            self, path_to_folder: AnyStr, data_file: AnyStr,
            tool: AnyStr, name: AnyStr, dest: AnyStr, params, source=None
    ):
        command = ["docker", "run", "--rm", "--entrypoint", "java", "-i",
                   f"{self.image.image_name.lower()}", "-cp", "classes:libs/*",
                   "org.entry.Dispatcher", "Replayer"]
        if source:
            command += ["-i", f"{source}"]
        command += ["-f", f"{tool}"] + params

        with open(f"{path_to_folder}/{data_file}", 'r') as input_file:
            result = subprocess.run(command, stdin=input_file, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"{dest}/{name}.{tool}")
                with open(f"{dest}/{name}.{tool}", "w") as f:
                    for line in filter(lambda x: not x.startswith(">W"), result.stdout.splitlines()):
                        f.write(line + "\n")
            else:
                raise ReplayerException("Replayer Failed")

    @staticmethod
    def conversion_scheme() -> List[Tuple[InputOutputTraceFormats, InputOutputTraceFormats]]:
        return [
            (InputOutputTraceFormats.MONPOLY, InputOutputTraceFormats.CSV),
            (InputOutputTraceFormats.MONPOLY, InputOutputTraceFormats.CSV_LINEAR),
            (InputOutputTraceFormats.MONPOLY, InputOutputTraceFormats.DEJAVU),
            (InputOutputTraceFormats.MONPOLY, InputOutputTraceFormats.DEJAVU_ENCODED),
            (InputOutputTraceFormats.MONPOLY, InputOutputTraceFormats.DEJAVU_LINEAR),

            (InputOutputTraceFormats.CSV, InputOutputTraceFormats.MONPOLY),
            (InputOutputTraceFormats.CSV, InputOutputTraceFormats.MONPOLY_LINEAR),
            (InputOutputTraceFormats.CSV, InputOutputTraceFormats.DEJAVU),
            (InputOutputTraceFormats.CSV, InputOutputTraceFormats.DEJAVU_ENCODED),
            (InputOutputTraceFormats.CSV, InputOutputTraceFormats.DEJAVU_LINEAR),

            (InputOutputTraceFormats.DEJAVU, InputOutputTraceFormats.MONPOLY),
            (InputOutputTraceFormats.DEJAVU, InputOutputTraceFormats.MONPOLY_LINEAR),
            (InputOutputTraceFormats.DEJAVU, InputOutputTraceFormats.CSV),
            (InputOutputTraceFormats.DEJAVU, InputOutputTraceFormats.CSV_LINEAR),
        ]
