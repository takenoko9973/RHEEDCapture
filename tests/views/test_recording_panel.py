from PySide6.QtTest import QSignalSpy
from pytestqt.qtbot import QtBot

from rheed_capture.presentation.qt.panels.recording import RecordingPanel


def test_recording_panel_converts_rate_when_switching_modes(qtbot: QtBot) -> None:
    """Rate mode切替時に表示中の値から次の入力値を換算する。"""
    panel = RecordingPanel(exposure_bounds=(1.0, 10000.0), gain_bounds=(0, 48))
    qtbot.addWidget(panel)
    mode_spy = QSignalSpy(panel.rate_mode_changed)
    fps_spy = QSignalSpy(panel.fps_changed)
    interval_spy = QSignalSpy(panel.interval_changed)

    panel.btn_rate_fps.click()
    assert mode_spy.at(0) == ["fps"]
    assert fps_spy.count() == 1
    assert fps_spy.at(0) == [10.0]
    assert panel.rate_value_stack.currentWidget() is panel.spin_fps
    assert panel.spin_fps.value() == 10.0

    panel.spin_fps.setValue(20.0)
    panel.btn_rate_interval.click()
    assert mode_spy.at(1) == ["interval"]
    assert interval_spy.count() == 1
    assert interval_spy.at(0) == [50.0]
    assert panel.rate_value_stack.currentWidget() is panel.spin_interval_ms
    assert panel.spin_interval_ms.value() == 50.0


def test_recording_panel_combines_hardware_and_capture_locks(qtbot: QtBot) -> None:
    """Rate入力はHardware modeと録画状態のどちらでも無効になる。"""
    panel = RecordingPanel(exposure_bounds=(1.0, 10000.0), gain_bounds=(0, 48))
    qtbot.addWidget(panel)

    panel.set_hardware_mode("hardware")
    assert panel.btn_rate_interval.isEnabled() is False
    assert panel.btn_rate_fps.isEnabled() is False
    assert panel.spin_interval_ms.isEnabled() is False
    assert panel.spin_fps.isEnabled() is False

    panel.set_capturing_state(True)
    panel.set_hardware_mode("software")
    assert panel.btn_rate_interval.isEnabled() is False
    assert panel.btn_rate_fps.isEnabled() is False

    panel.set_capturing_state(False)
    assert panel.btn_rate_interval.isEnabled() is True
    assert panel.btn_rate_fps.isEnabled() is True
