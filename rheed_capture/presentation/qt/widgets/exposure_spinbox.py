import math

from PySide6.QtWidgets import QDoubleSpinBox

MIN_EXPOSURE_ARROW_STEP = 0.01
EXPOSURE_ARROW_STEP_DIGITS_BELOW_TOP = 2


def exposure_arrow_step(value: float) -> float:
    if value <= 0:
        return MIN_EXPOSURE_ARROW_STEP

    # 矢印操作では上位桁を荒く変えず、1200なら10 ms、23なら0.1 ms単位で微調整する。
    highest_digit_power = math.floor(math.log10(value))
    step = 10 ** (highest_digit_power - EXPOSURE_ARROW_STEP_DIGITS_BELOW_TOP)
    return max(MIN_EXPOSURE_ARROW_STEP, step)


class ExposureSpinBox(QDoubleSpinBox):
    def stepBy(self, steps: int) -> None:  # noqa: N802
        # QtはstepBy()内でsingleStepを参照するため、現在値に合わせて先に更新する。
        self.setSingleStep(exposure_arrow_step(self.value()))
        super().stepBy(steps)
