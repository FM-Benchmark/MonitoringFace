import subprocess
from typing import AnyStr, List, Tuple, Dict, Any

from Infrastructure.AutoConversion.InputOutputPolicyFormats import InputOutputPolicyFormats
from Infrastructure.Builders.ProcessorBuilder.ImageManager import Processor, ImageManager
from Infrastructure.Builders.ProcessorBuilder.PolicyConverters.PolicyConverterTemplate import PolicyConverterTemplate


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
        cmd_params = params["cmd_params"] if "cmd_params" in params else ["-n", "-e", "e"]
        command = ["docker", "run", "--rm", "-iv", f"{path_to_folder}:/home/qtl-translator/work",
                   f"{self.image.image_name.lower()}"] + cmd_params + [input_file]

        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            with open(f"{path_to_output_folder}/{output_file}", "w") as f:
                for line in result.stdout.splitlines():
                    f.write(line + "\n")
        else:
            raise QTLConverterException("QTLTranslator Failed")
        return command  # exact argv, recorded in the provenance manifest

    @staticmethod
    def conversion_scheme() -> List[Tuple[InputOutputPolicyFormats, InputOutputPolicyFormats]]:
        return [
            (InputOutputPolicyFormats.MFOTL, InputOutputPolicyFormats.QTL),
            (InputOutputPolicyFormats.NEGATED_MFOTL, InputOutputPolicyFormats.QTL),
        ]


class QTLConverterException(Exception):
    pass
