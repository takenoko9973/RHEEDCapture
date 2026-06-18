from rheed_capture.presentation.qt.widgets.exposure_spinbox import exposure_arrow_step


def test_exposure_arrow_step_uses_two_digits_below_highest_digit() -> None:
    assert exposure_arrow_step(1200.0) == 10.0
    assert exposure_arrow_step(23.0) == 0.1
    assert exposure_arrow_step(0.5) == 0.01
