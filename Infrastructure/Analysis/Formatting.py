import re


def parse_wall_time(s: str) -> float | str:
    if s is None:
        return "N/A"
    
    s = s.strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)

    m = re.fullmatch(r"(\d+)m\s+(\d+(\.\d+)?)s", s)
    if m:
        minutes = int(m.group(1))
        seconds = float(m.group(2))
        return minutes * 60 + seconds

    m = re.fullmatch(r"(\d+)h\s+(\d+)m\s+(\d+(\.\d+)?)s", s)
    if m:
        hours = int(m.group(1))
        minutes = int(m.group(2))
        seconds = float(m.group(3))
        return hours * 3600 + minutes * 60 + seconds

    if ":" in s:
        parts = s.split(":")
        parts = [float(p) for p in parts]

        if len(parts) == 2:
            mm, ss = parts
            return mm * 60 + ss
        elif len(parts) == 3:
            hh, mm, ss = parts
            return hh * 3600 + mm * 60 + ss

    if s.endswith("s"):
        return float(s[:-1])
    return "N/A"


def parse_memory(s: str) -> str:
    if s is None:
        return "N/A"
    return s.strip()

def parse_cpu(s: str) -> str:
    if s is None:
        return "N/A"
    return s.strip()