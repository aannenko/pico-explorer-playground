import builtins
import sys
import types
from pathlib import Path

PICO_SRC = Path(__file__).resolve().parent.parent / "pico"
if str(PICO_SRC) not in sys.path:
    sys.path.insert(0, str(PICO_SRC))

# MicroPython provides `const`; CPython doesn't.
if not hasattr(builtins, "const"):
    setattr(builtins, "const", lambda value: value)

# Provide a minimal `picographics` stub so CPython unit tests
# can import modules that only use it for typing/attribute access.
if "picographics" not in sys.modules:
    picographics_stub = types.ModuleType("picographics")
    picographics_stub.PicoGraphics = object
    sys.modules["picographics"] = picographics_stub

# MicroPython-only modules used by pico code. Provide minimal stubs so imports
# work under CPython unit tests.
if "micropython" not in sys.modules:
    micropython_stub = types.ModuleType("micropython")

    def _const(value):
        # MicroPython's const() is an optimization hint; in CPython it's a no-op.
        return value

    def _native(func):
        # No-op decorator for CPython tests.
        return func

    def _schedule(callback, arg):
        # In unit tests we default to instantaneous execution.
        callback(arg)

    micropython_stub.const = _const
    micropython_stub.native = _native
    micropython_stub.schedule = _schedule
    sys.modules["micropython"] = micropython_stub

if "machine" not in sys.modules:
    machine_stub = types.ModuleType("machine")

    class _Timer:
        ONE_SHOT = 0
        PERIODIC = 1

        def __init__(self, _timer_id=-1):
            self._timer_id = _timer_id

        def init(self, **_kwargs):
            return None

        def deinit(self):
            return None

    machine_stub.Timer = _Timer
    sys.modules["machine"] = machine_stub
