from enum import Enum


class InputOutputTraceFormats(Enum):
    CSV = "csv"
    OOO_CSV = "ooo-csv"
    CSV_LINEAR = "csv-linear"
    MONPOLY_LINEAR = "monpoly-linear"
    MONPOLY = "monpoly"
    DEJAVU = "dejavu"
    DEJAVU_ENCODED = "dejavu-encoded"
    DEJAVU_LINEAR = "dejavu-linear"
    SRV_TRACE = "srv-trace"


def str_to_trace_inout_format(format_str: str) -> InputOutputTraceFormats:
    format_str = format_str.lower()
    if format_str == "csv":
        return InputOutputTraceFormats.CSV
    if format_str == "ooo-csv":
        return InputOutputTraceFormats.OOO_CSV
    elif format_str == "csv-linear":
        return InputOutputTraceFormats.CSV_LINEAR
    elif format_str == "monpoly-linear":
        return InputOutputTraceFormats.MONPOLY_LINEAR
    elif format_str == "monpoly":
        return InputOutputTraceFormats.MONPOLY
    elif format_str == "dejavu":
        return InputOutputTraceFormats.DEJAVU
    elif format_str == "dejavu-encoded":
        return InputOutputTraceFormats.DEJAVU_ENCODED
    elif format_str == "dejavu-linear":
        return InputOutputTraceFormats.DEJAVU_LINEAR
    elif format_str == "srv-trace":
        return InputOutputTraceFormats.SRV_TRACE
    else:
        raise ValueError(f"Unknown input/output format: {format_str}")


def trace_inout_format_to_str(format_enum: InputOutputTraceFormats) -> str:
    if format_enum == InputOutputTraceFormats.CSV:
        return "csv"
    elif format_enum == InputOutputTraceFormats.OOO_CSV:
        return "ooo-csv"
    elif format_enum == InputOutputTraceFormats.CSV_LINEAR:
        return "csv-linear"
    elif format_enum == InputOutputTraceFormats.MONPOLY_LINEAR:
        return "monpoly-linear"
    elif format_enum == InputOutputTraceFormats.MONPOLY:
        return "monpoly"
    elif format_enum == InputOutputTraceFormats.DEJAVU:
        return "dejavu"
    elif format_enum == InputOutputTraceFormats.DEJAVU_ENCODED:
        return "dejavu-encoded"
    elif format_enum == InputOutputTraceFormats.DEJAVU_LINEAR:
        return "dejavu-linear"
    elif format_enum == InputOutputTraceFormats.SRV_TRACE:
        return "srv-trace"
    else:
        raise ValueError(f"Unknown input/output format enum: {format_enum}")