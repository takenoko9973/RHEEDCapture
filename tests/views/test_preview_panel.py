from PySide6.QtTest import QSignalSpy
from pytestqt.qtbot import QtBot

from rheed_capture.presentation.qt.panels.preview import PreviewPanel
from rheed_capture.presentation.qt.widgets.exposure_slider import (
    exposure_to_slider,
    slider_to_exposure,
)


def test_exposure_slider_conversion_uses_logarithmic_scale() -> None:
    """露光時間とSlider位置を対数スケールで相互変換する。"""
    bounds = (1.0, 100.0)

    assert exposure_to_slider(10.0, bounds, 1000) == 500
    assert slider_to_exposure(500, bounds, 1000) == 10.0
    assert exposure_to_slider(0.5, bounds, 1000) == 0
    assert slider_to_exposure(1000, bounds, 1000) == 100.0


def test_preview_panel_syncs_inputs_with_camera_signal_timing(qtbot: QtBot) -> None:
    """SpinBoxは即時通知し、Sliderはrelease時だけカメラ値を通知する。"""
    panel = PreviewPanel(expo_bounds=(1.0, 100.0), gain_bounds=(0, 40))
    qtbot.addWidget(panel)
    exposure_spy = QSignalSpy(panel.exposure_changed)
    gain_spy = QSignalSpy(panel.gain_changed)

    panel.spin_expo.setValue(10.0)
    assert panel.slider_expo.value() == 500
    assert exposure_spy.count() == 1
    assert exposure_spy.at(0) == [10.0]

    panel.slider_expo.setValue(750)
    assert exposure_spy.count() == 1
    panel.slider_expo.sliderReleased.emit()
    assert exposure_spy.count() == 2
    assert exposure_spy.at(1) == [panel.spin_expo.value()]

    panel.spin_gain.setValue(12)
    assert panel.slider_gain.value() == 12
    assert gain_spy.count() == 1
    panel.slider_gain.setValue(15)
    assert panel.spin_gain.value() == 15
    assert gain_spy.count() == 1
    panel.slider_gain.sliderReleased.emit()
    assert gain_spy.at(1) == [15]


def test_preview_panel_keeps_display_controls_enabled_during_capture(
    qtbot: QtBot,
) -> None:
    """撮影中もCLAHEとGridを操作でき、カメラ条件だけをロックする。"""
    panel = PreviewPanel(expo_bounds=(1.0, 100.0), gain_bounds=(0, 40))
    qtbot.addWidget(panel)
    panel.chk_show_grid.setChecked(True)
    clahe_spy = QSignalSpy(panel.clahe_toggled)

    panel.set_controls_enabled(False)

    assert panel.spin_expo.isEnabled() is False
    assert panel.slider_expo.isEnabled() is False
    assert panel.spin_gain.isEnabled() is False
    assert panel.slider_gain.isEnabled() is False
    assert panel.chk_processing.isEnabled() is True
    assert panel.chk_show_grid.isEnabled() is True
    assert panel.cmb_grid_shape.isEnabled() is True

    panel.chk_processing.setChecked(True)
    assert clahe_spy.count() == 1
    assert clahe_spy.at(0) == [True]


def test_preview_panel_applies_and_emits_grid_settings(qtbot: QtBot) -> None:
    """Gridの有効状態と形状を通知し、保存値を往復する。"""
    panel = PreviewPanel(expo_bounds=(1.0, 100.0), gain_bounds=(0, 40))
    qtbot.addWidget(panel)
    enabled_spy = QSignalSpy(panel.grid_enabled_changed)
    shape_spy = QSignalSpy(panel.grid_shape_changed)

    panel.chk_show_grid.setChecked(True)
    panel.cmb_grid_shape.setCurrentText("8x8")

    assert enabled_spy.at(0) == [True]
    assert shape_spy.at(0) == [8, 8]

    panel.apply_grid_settings(True, 2, 4)
    settings = panel.get_grid_settings_to_save()
    assert settings.show_grid is True
    assert settings.rows == 2
    assert settings.cols == 4
    assert enabled_spy.count() == 1
    assert shape_spy.count() == 1
