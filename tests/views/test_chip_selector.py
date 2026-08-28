from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QToolButton
from pytestqt.qtbot import QtBot

from rheed_capture.presentation.qt.widgets.chip_selector import ChipSelector


def _button(selector: ChipSelector, text: str) -> QToolButton:
    """表示文字列で公開Widget tree内のチップを取得する。"""
    return next(button for button in selector.findChildren(QToolButton) if button.text() == text)


def test_chip_selector_emits_values_in_candidate_order(qtbot: QtBot) -> None:
    """選択順に依存せず、候補リスト順の選択値を通知する。"""
    selector = ChipSelector()
    qtbot.addWidget(selector)
    selector.set_values([10.0, 20.0, 30.0], [20.0])
    selection_spy = QSignalSpy(selector.selection_changed)

    _button(selector, "30").click()
    _button(selector, "10").click()

    assert selection_spy.at(0) == [[20.0, 30.0]]
    assert selection_spy.at(1) == [[10.0, 20.0, 30.0]]
    assert selector.selected_values() == [10.0, 20.0, 30.0]


def test_chip_selector_parent_enabled_state_applies_to_chips(qtbot: QtBot) -> None:
    """Widget標準のenabled伝播で全チップが無効になる。"""
    selector = ChipSelector()
    qtbot.addWidget(selector)
    selector.set_values([10.0, 20.0], [])

    selector.setEnabled(False)

    assert all(not button.isEnabled() for button in selector.findChildren(QToolButton))
