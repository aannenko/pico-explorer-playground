from breakout_bme69x import BreakoutBME69X, STATUS_HEATER_STABLE, FILTER_COEFF_3, OVERSAMPLING_1X, OVERSAMPLING_2X, STANDBY_TIME_1000_MS  # type: ignore
from pimoroni import PICO_EXPLORER_I2C_PINS  # type: ignore
from pimoroni_i2c import PimoroniI2C  # type: ignore


class BME690Reader:
    def __init__(self, temp_offset: float, hum_offset: float) -> None:
        self._temp_offset = temp_offset
        self._hum_offset = hum_offset

        self._bme = BreakoutBME69X(PimoroniI2C(**PICO_EXPLORER_I2C_PINS))
        self._bme.configure(
            FILTER_COEFF_3,
            STANDBY_TIME_1000_MS,
            OVERSAMPLING_2X,
            OVERSAMPLING_2X,
            OVERSAMPLING_1X,
        )

    def read(self) -> tuple[float, float, float, float, str]:
        temp, press, hum, gas_r, status = self._bme.read()[0:5]
        temp += self._temp_offset
        hum += self._hum_offset
        heater = "Stable" if status & STATUS_HEATER_STABLE else "Unstable"

        return (temp, press / 100, hum, gas_r / 1000, heater)  # C, mb, %, kOhm, status
