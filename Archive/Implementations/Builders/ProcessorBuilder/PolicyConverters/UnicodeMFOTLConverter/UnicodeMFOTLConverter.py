import re
from typing import List, Tuple, Dict, Any

from Infrastructure.AutoConversion.InputOutputPolicyFormats import InputOutputPolicyFormats
from Infrastructure.Builders.ProcessorBuilder.PolicyConverters.PolicyConverterTemplate import PolicyConverterTemplate


UNICODE_TO_STRING = [
    ("∞", "*"), ("⊤", " TRUE "), ("⊥", " FALSE "), ("¬", " NOT "), ("∧", " AND "),
    ("∨", " OR "), ("→", " IMPLIES "), ("↔", " IFF "), ("∃", " EXISTS "), ("∀", " FORALL "),
    ("S", " SINCE "), ("U", " UNTIL "), ("●", " PREV "), ("○", " NEXT "), ("⧫", " ONCE "),
    ("◊", " EVENTUALLY "), ("■", " ALWAYS "), ("□", " HISTORICALLY ")
]


def bounded_pattern(symbol: str) -> str:
    pattern = re.escape(symbol)
    if symbol[:1].isalnum() or symbol[:1] == "_":
        pattern = r"\b" + pattern
    if symbol[-1:].isalnum() or symbol[-1:] == "_":
        pattern = pattern + r"\b"
    return pattern


class UnicodeMFOTLConverterException(Exception):
    pass


class UnicodeMFOTLConverter(PolicyConverterTemplate):
    def __init__(self, name, path_to_project):
        pass

    def auto_convert(self, path_to_folder: str, input_file: str, path_to_output_folder: str, output_file: str,
                     source: InputOutputPolicyFormats, target: InputOutputPolicyFormats, params: Dict[str, Any]):
        with open(f"{path_to_folder}/{input_file}", 'r') as input_file:
            src_policy = input_file.read()

        unicode_to_mfotl = ((source == InputOutputPolicyFormats.UNICODE_MFOTL or source == InputOutputPolicyFormats.NEGATED_UNICODE_MFOTL)
                            and (target == InputOutputPolicyFormats.MFOTL or target == InputOutputPolicyFormats.NEGATED_MFOTL))

        mfotl_to_unicode = ((source == InputOutputPolicyFormats.MFOTL or source == InputOutputPolicyFormats.NEGATED_MFOTL)
                            and (target == InputOutputPolicyFormats.UNICODE_MFOTL or target == InputOutputPolicyFormats.NEGATED_UNICODE_MFOTL))

        if unicode_to_mfotl or mfotl_to_unicode:
            for unicode_symbol, string_symbol in UNICODE_TO_STRING:
                if unicode_to_mfotl:
                    src_policy = re.sub(bounded_pattern(unicode_symbol), string_symbol, src_policy)
                else:
                    src_policy = re.sub(bounded_pattern(string_symbol), unicode_symbol, src_policy)
            with open(f"{path_to_folder}/{output_file}", 'w') as f:
                f.write(src_policy)
        else:
            raise UnicodeMFOTLConverterException(f"Incompatible conversion from {source} to {target}")

    @staticmethod
    def conversion_scheme() -> List[Tuple[InputOutputPolicyFormats, InputOutputPolicyFormats]]:
        return [
            (InputOutputPolicyFormats.UNICODE_MFOTL, InputOutputPolicyFormats.MFOTL),
            (InputOutputPolicyFormats.NEGATED_UNICODE_MFOTL, InputOutputPolicyFormats.NEGATED_MFOTL),
            (InputOutputPolicyFormats.MFOTL, InputOutputPolicyFormats.UNICODE_MFOTL),
            (InputOutputPolicyFormats.NEGATED_MFOTL, InputOutputPolicyFormats.NEGATED_UNICODE_MFOTL),
        ]
