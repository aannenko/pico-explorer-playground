import builtins
import sys
from pathlib import Path

PICO_SRC = Path(__file__).resolve().parent.parent / "pico"
if str(PICO_SRC) not in sys.path:
    sys.path.insert(0, str(PICO_SRC))

# MicroPython provides `const`; CPython doesn't.
if not hasattr(builtins, "const"):
    setattr(builtins, "const", lambda value: value)
