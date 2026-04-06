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

    def _native(func):
        # No-op decorator for CPython tests.
        return func

    def _schedule(callback, arg):
        # In unit tests we default to instantaneous execution.
        callback(arg)

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

    class _Pin:
        def __init__(self, pin_id, *args, **kwargs):
            self._pin_id = pin_id

    class _PWM:
        def __init__(self, pin, *args, **kwargs):
            self._pin = pin
            self._freq = 0
            self._duty = 0

        def freq(self, f=None):
            if f is not None:
                self._freq = f
            return self._freq

        def duty_u16(self, d=None):
            if d is not None:
                self._duty = d
            return self._duty

        def deinit(self):
            pass

    machine_stub.Timer = _Timer
    machine_stub.Pin = _Pin
    machine_stub.PWM = _PWM
    sys.modules["machine"] = machine_stub

# Sensor driver deps (only available on-device). Provide minimal stubs so
# importing `services.sensors.pimoroni_bme690` works under CPython unit tests.
if "pimoroni" not in sys.modules:
    pimoroni_stub = types.ModuleType("pimoroni")
    pimoroni_stub.PICO_EXPLORER_I2C_PINS = {"sda": 0, "scl": 1}  # type: ignore[attr-defined]
    # Note: __path__ is NOT set here — the built-in pimoroni module is not a
    # package. Explorer-specific code lives under pico/services/ with naming

    class _Button:
        def __init__(self, pin):
            self._pin = pin

        def read(self):
            return False

    pimoroni_stub.Button = _Button
    sys.modules["pimoroni"] = pimoroni_stub

if "pimoroni_i2c" not in sys.modules:
    pimoroni_i2c_stub = types.ModuleType("pimoroni_i2c")

    class _PimoroniI2C:  # minimal constructor-compatible shim
        def __init__(self, **_kwargs):
            pass

    pimoroni_i2c_stub.PimoroniI2C = _PimoroniI2C
    sys.modules["pimoroni_i2c"] = pimoroni_i2c_stub

if "breakout_bme69x" not in sys.modules:
    breakout_stub = types.ModuleType("breakout_bme69x")

    breakout_stub.STATUS_HEATER_STABLE = 1
    breakout_stub.FILTER_COEFF_3 = 3
    breakout_stub.OVERSAMPLING_1X = 1
    breakout_stub.OVERSAMPLING_2X = 2
    breakout_stub.STANDBY_TIME_1000_MS = 1000

    class _BreakoutBME69X:  # minimal API shim used by `BME690Reader`
        def __init__(self, _i2c):
            pass

        def configure(self, *_args):
            return None

        def read(self):
            # Return a tuple long enough for [0:5] slicing.
            return (0.0, 0.0, 0.0, 0.0, 0)

    breakout_stub.BreakoutBME69X = _BreakoutBME69X
    sys.modules["breakout_bme69x"] = breakout_stub

if "ntptime" not in sys.modules:
    ntptime_stub = types.ModuleType("ntptime")
    ntptime_stub.settime = lambda: None  # type: ignore[attr-defined]
    sys.modules["ntptime"] = ntptime_stub

if "network" not in sys.modules:
    network_stub = types.ModuleType("network")

    class _WLAN:
        def __init__(self, _mode):
            pass
        def active(self, _state=None):
            return True
        def isconnected(self):
            return False
        def connect(self, _ssid, _password):
            pass
        def disconnect(self):
            pass
        def status(self):
            return 0
        def config(self, _key):
            return ""

    network_stub.WLAN = _WLAN
    network_stub.STA_IF = 0
    network_stub.STAT_GOT_IP = 3
    network_stub.STAT_WRONG_PASSWORD = 4
    network_stub.STAT_CONNECTING = 1
    network_stub.STAT_NO_AP_FOUND = 2
    network_stub.STAT_CONNECT_FAIL = 5
    sys.modules["network"] = network_stub
