import math

from rheed_capture.utils import round_sig_figs


def exposure_to_slider(
    exposure_ms: float,
    exposure_bounds: tuple[float, float],
    slider_steps: int,
) -> int:
    """露光時間を対数スケールのSlider位置へ変換する。"""
    exposure_min, exposure_max = _integer_bounds(exposure_bounds)
    if exposure_ms <= exposure_min:
        return 0
    if exposure_ms >= exposure_max:
        return slider_steps

    log_min = math.log10(exposure_min)
    log_max = math.log10(exposure_max)
    log_value = math.log10(exposure_ms)
    position = (log_value - log_min) / (log_max - log_min)
    return round(position * slider_steps)


def slider_to_exposure(
    slider_value: int,
    exposure_bounds: tuple[float, float],
    slider_steps: int,
) -> float:
    """対数スケールのSlider位置を露光時間msへ変換する。"""
    exposure_min, exposure_max = _integer_bounds(exposure_bounds)
    if slider_value <= 0:
        return float(exposure_min)
    if slider_value >= slider_steps:
        return float(exposure_max)

    log_min = math.log10(exposure_min)
    log_max = math.log10(exposure_max)
    position = slider_value / slider_steps
    log_value = log_min + position * (log_max - log_min)
    return round_sig_figs(10**log_value, 2)


def _integer_bounds(exposure_bounds: tuple[float, float]) -> tuple[int, int]:
    """Slider変換で使う整数msの上下限を返す。"""
    exposure_min, exposure_max = exposure_bounds
    return math.ceil(exposure_min), math.floor(exposure_max)
