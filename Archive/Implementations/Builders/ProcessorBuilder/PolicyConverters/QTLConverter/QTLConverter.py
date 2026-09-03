import os
import subprocess
from typing import AnyStr, List, Tuple, Dict, Any

from Infrastructure.AutoConversion.InputOutputPolicyFormats import InputOutputPolicyFormats
from Infrastructure.Builders.ProcessorBuilder.ImageManager import Processor, ImageManager
from Infrastructure.Builders.ProcessorBuilder.PolicyConverters.PolicyConverterTemplate import PolicyConverterTemplate
from Infrastructure.constants import POLICY_CONSTANTS_APPLIED, POLICY_CONSTANTS_COUNT, POLICY_CONSTANTS_FILE

DEFAULT_CMD_PARAMS = ["-n", "-e", "e"]
# The translator writes the policy's constants to <dom predicate>.dom in its working
# directory, which is the mounted folder, so the file is next to the converted policy.
DEFAULT_DOM_PREDICATE = "_dom"
DOM_FILE_SUFFIX = ".dom"


def dom_file_name(cmd_params: List[str]) -> str:
    """Name of the constants file the translator writes, given its arguments."""
    for flag, value in zip(cmd_params, cmd_params[1:]):
        if flag in ("-d", "--dom"):
            return value + DOM_FILE_SUFFIX
    return DEFAULT_DOM_PREDICATE + DOM_FILE_SUFFIX


def count_registration_events(path: str) -> int:
    """Number of events the constants file registers: one per argument tuple, so
    `_dom(1)(2)(5)` registers three. Parentheses are counted outside of the
    translator's double-quoted string constants."""
    count = 0
    depth = 0
    in_quotes = False
    with open(path, "r") as f:
        for char in f.read():
            if in_quotes:
                in_quotes = char != '"'
            elif char == '"':
                in_quotes = True
            elif char == "(":
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1
                if depth == 0:
                    count += 1
    return count


class QTLConverter(PolicyConverterTemplate):
    def __init__(self, name, path_to_project):
        self.image = ImageManager(name, Processor.PolicyConverters, path_to_project)

    def convert(self, path_to_folder: AnyStr, data_file: AnyStr, tool: AnyStr, name: AnyStr, dest: AnyStr, params):
        command = ["docker", "run", "--rm", "-iv", f"{path_to_folder}:/home/qtl-translator/work",
                   f"{self.image.image_name.lower()}"] + params + [data_file]

        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            with open(f"{dest}/{name}.{tool}", "w") as f:
                for line in result.stdout.splitlines():
                    f.write(line + "\n")
        else:
            raise QTLConverterException("QTLTranslator Failed")

    def auto_convert(self, path_to_folder: str, input_file: str, path_to_output_folder: str, output_file: str,
                     source: InputOutputPolicyFormats, target: InputOutputPolicyFormats, params: Dict[str, Any]):
        cmd_params = params["cmd_params"] if "cmd_params" in params else DEFAULT_CMD_PARAMS
        dom_file = dom_file_name(cmd_params)
        dom_path = os.path.join(path_to_folder, dom_file)
        # The translator writes the file only for a policy that compares a variable
        # against a constant, and params outlive a single setting: without this, a
        # constant-free policy would inherit the previous policy's constants.
        for key in (POLICY_CONSTANTS_FILE, POLICY_CONSTANTS_COUNT, POLICY_CONSTANTS_APPLIED):
            params.pop(key, None)
        if os.path.exists(dom_path):
            os.remove(dom_path)

        command = ["docker", "run", "--rm", "-iv", f"{path_to_folder}:/home/qtl-translator/work",
                   f"{self.image.image_name.lower()}"] + cmd_params + [input_file]

        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            with open(f"{path_to_output_folder}/{output_file}", "w") as f:
                for line in result.stdout.splitlines():
                    f.write(line + "\n")
        else:
            raise QTLConverterException("QTLTranslator Failed")

        # Hand the extracted constants
        # to the trace conversion, to prepend them to the trace.
        if os.path.isfile(dom_path):
            registered = count_registration_events(dom_path)
            if registered == 0:
                raise QTLConverterException(
                    f"QTLTranslator wrote {dom_file} but it registers no constants; "
                    f"the trace conversion cannot put the policy's constants in range"
                )
            params[POLICY_CONSTANTS_FILE] = dom_file
            params[POLICY_CONSTANTS_COUNT] = registered
        return command  # exact argv, recorded in the provenance manifest

    @staticmethod
    def conversion_scheme() -> List[Tuple[InputOutputPolicyFormats, InputOutputPolicyFormats]]:
        return [
            (InputOutputPolicyFormats.MFOTL, InputOutputPolicyFormats.QTL),
            (InputOutputPolicyFormats.NEGATED_MFOTL, InputOutputPolicyFormats.QTL),
        ]


class QTLConverterException(Exception):
    pass
