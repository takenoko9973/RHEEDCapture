from PySide6.QtTest import QSignalSpy
from pytestqt.qtbot import QtBot

from rheed_capture.presentation.qt.panels.capture_chips import CaptureChipsPanel


def test_capture_chips_panel_parses_and_emits_candidate_values(qtbot: QtBot) -> None:
    """カンマ区切り入力を型付き候補値へ変換して通知する。"""
    panel = CaptureChipsPanel()
    qtbot.addWidget(panel)
    panel.set_values([10.0], [0])
    exposure_spy = QSignalSpy(panel.exposure_values_changed)
    gain_spy = QSignalSpy(panel.gain_values_changed)

    panel.edit_exposure_values.setText("10, 50, 100")
    panel.edit_exposure_values.editingFinished.emit()
    panel.edit_gain_values.setText("0, 5")
    panel.edit_gain_values.editingFinished.emit()

    assert exposure_spy.at(0) == [[10.0, 50.0, 100.0]]
    assert gain_spy.at(0) == [[0, 5]]
    assert panel.exposure_ms_values() == [10.0, 50.0, 100.0]
    assert panel.gain_values() == [0, 5]


def test_capture_chips_panel_rolls_back_invalid_input(qtbot: QtBot) -> None:
    """不正入力では候補値を変更せず、直前の表示へ戻す。"""
    panel = CaptureChipsPanel()
    qtbot.addWidget(panel)
    panel.set_values([10.0, 50.0], [0, 5])
    error_spy = QSignalSpy(panel.error_occurred)

    panel.edit_exposure_values.setText("")
    panel.edit_exposure_values.editingFinished.emit()
    panel.edit_gain_values.setText("0, G5")
    panel.edit_gain_values.editingFinished.emit()

    assert error_spy.count() == 2
    assert panel.edit_exposure_values.text() == "10, 50"
    assert panel.edit_gain_values.text() == "0, 5"
    assert panel.exposure_ms_values() == [10.0, 50.0]
    assert panel.gain_values() == [0, 5]
