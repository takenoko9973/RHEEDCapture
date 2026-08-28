import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QToolButton
from pytestqt.qtbot import QtBot

from rheed_capture.presentation.qt.panels.angle_scan import AngleScanPanel
from rheed_capture.presentation.qt.panels.sequence import SequencePanel
from rheed_capture.presentation.qt.widgets.chip_selector import ChipSelector


def _button(selector: ChipSelector, text: str) -> QToolButton:
    """表示文字列で公開Widget tree内のチップを取得する。"""
    return next(button for button in selector.findChildren(QToolButton) if button.text() == text)


@pytest.mark.parametrize("panel_type", [SequencePanel, AngleScanPanel])
def test_capture_panel_forwards_chip_selection(panel_type: type, qtbot: QtBot) -> None:
    """撮影Panelが候補値を表示し、チップ選択を外部へ通知する。"""
    panel = panel_type()
    qtbot.addWidget(panel)
    panel.update_exposure_values([10.0, 20.0], [10.0])
    panel.update_gain_values([0, 1], [0])
    exposure_spy = QSignalSpy(panel.exposure_selection_changed)
    gain_spy = QSignalSpy(panel.gain_selection_changed)

    _button(panel.exposure_selector, "20").click()
    _button(panel.gain_selector, "0").click()

    assert exposure_spy.at(0) == [[10.0, 20.0]]
    assert gain_spy.at(0) == [[]]


@pytest.mark.parametrize("panel_type", [SequencePanel, AngleScanPanel])
def test_capture_panel_forwards_start_request(panel_type: type, qtbot: QtBot) -> None:
    """撮影PanelのStart操作を公開Signalへ転送する。"""
    panel = panel_type()
    qtbot.addWidget(panel)
    start_spy = QSignalSpy(panel.start_requested)

    panel.btn_start.click()

    assert start_spy.count() == 1
