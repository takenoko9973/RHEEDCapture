from PySide6.QtWidgets import QFrame
from pytestqt.qtbot import QtBot

from rheed_capture.presentation.qt.widgets.collapsible_section import CollapsibleSection


def test_collapsible_section_toggles_content_visibility(qtbot: QtBot) -> None:
    """折りたたみ状態と内容Widgetの表示状態を同期する。"""
    content = QFrame()
    section = CollapsibleSection("Capture", content)
    qtbot.addWidget(section)

    section.set_expanded(False)
    assert section.is_expanded() is False
    assert content.isHidden() is True

    section.toggle_button.click()
    assert section.is_expanded() is True
    assert content.isHidden() is False
