from enum import Enum


class InputOutputPolicyFormats(Enum):
    MFOTL = "mfotl"
    NEGATED_MFOTL = "negated-mfotl"
    UNICODE_MFOTL = "unicode-mfotl"
    NEGATED_UNICODE_MFOTL = "negated-unicode-mfotl"
    QTL = "qtl"
    SRV_POLICY = "srv-policy"
    OOO_FRAGMENT = "ooo-fragment"


def str_to_policy_inout_format(format_str: str) -> InputOutputPolicyFormats:
    format_str = format_str.lower()
    if format_str == "mfotl":
        return InputOutputPolicyFormats.MFOTL
    elif format_str == "negated-mfotl":
        return InputOutputPolicyFormats.NEGATED_MFOTL
    elif format_str == "unicode-mfotl":
        return InputOutputPolicyFormats.UNICODE_MFOTL
    elif format_str == "negated-unicode-mfotl":
        return InputOutputPolicyFormats.NEGATED_UNICODE_MFOTL
    elif format_str == "qtl":
        return InputOutputPolicyFormats.QTL
    elif format_str == "srv-policy":
        return InputOutputPolicyFormats.SRV_POLICY
    elif format_str == "ooo-fragment":
        return InputOutputPolicyFormats.OOO_FRAGMENT
    else:
        raise ValueError(f"Unknown input/output policy format: {format_str}")


def policy_inout_format_to_str(formats: InputOutputPolicyFormats) -> str:
    if formats == InputOutputPolicyFormats.MFOTL:
        return "mfotl"
    elif formats == InputOutputPolicyFormats.NEGATED_MFOTL:
        return "negated-mfotl"
    elif formats == InputOutputPolicyFormats.UNICODE_MFOTL:
        return "unicode-mfotl"
    elif formats == InputOutputPolicyFormats.NEGATED_UNICODE_MFOTL:
        return "negated-unicode-mfotl"
    elif formats == InputOutputPolicyFormats.QTL:
        return "qtl"
    elif formats == InputOutputPolicyFormats.SRV_POLICY:
        return "srv-policy"
    elif formats == InputOutputPolicyFormats.OOO_FRAGMENT:
        return "ooo-fragment"
    else:
        raise ValueError(f"Unknown input/output policy format enum: {formats}")
