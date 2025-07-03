from pathlib import Path
import docker

import warnings
from urllib3.exceptions import NotOpenSSLWarning
warnings.filterwarnings("ignore", category=NotOpenSSLWarning)

def get_all_tools() -> list[str]:
    script_dir = Path(__file__).parent
    tool_dir = script_dir.parent / "Tools"

    tool_names = []
    for subfolder in tool_dir.iterdir():
        if subfolder.is_dir():
            prop_file = subfolder / "tool.properties"
            with open(prop_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    # Look for the name key
                    if line.startswith('name='):
                        tool_name = line.split('=', 1)[1].strip()
                        tool_names.append(tool_name)
                        break

    return tool_names

def main():
    print(get_all_tools())
    return 0