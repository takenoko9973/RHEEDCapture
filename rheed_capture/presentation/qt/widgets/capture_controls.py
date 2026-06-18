from PySide6.QtWidgets import QFrame, QLabel, QPushButton


def configure_capture_buttons(
    start_button: QPushButton,
    cancel_button: QPushButton,
) -> None:
    start_button.setMinimumHeight(34)
    start_button.setMinimumWidth(180)
    start_button.setDefault(True)

    font = start_button.font()
    font.setBold(True)
    start_button.setFont(font)

    cancel_button.setMinimumHeight(34)
    cancel_button.setEnabled(False)


def configure_next_capture_label(label: QLabel) -> None:
    label.setFrameShape(QFrame.Shape.StyledPanel)
    label.setFrameShadow(QFrame.Shadow.Sunken)
    label.setMinimumHeight(26)
    label.setMinimumWidth(120)
    label.setStyleSheet("QLabel { padding: 3px 8px; background: #fafafa; }")
