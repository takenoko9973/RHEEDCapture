from pytestqt.qtbot import QtBot

from rheed_capture.views.components.sequence_panel import SequencePanel


def test_sequence_panel_next_preview_label_updates(qtbot: QtBot) -> None:
    panel = SequencePanel()
    qtbot.addWidget(panel)

    assert panel.lbl_next_sequence_preview.text() == "image_001"

    panel.update_next_sequence_preview("image_042")
    assert panel.lbl_next_sequence_preview.text() == "image_042"
