"""main.py — PyCharm entry point for the CSI-275 Final Project.

Running this file will execute the full test suite comparing the
original and refactored implementations side by side.

To run the chat application itself:
  Server  ->  python original/server.py   OR  python refactored/server.py
  Client  ->  python original/client.py   OR  python refactored/client.py
"""

import runpy
import sys
from pathlib import Path

# Make sure the project root is on the path so test_comparison.py
# can find the original/ and refactored/ folders.
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    runpy.run_path(str(ROOT / "test_comparison.py"), run_name="__main__")