from PySide6.QtWidgets import QPushButton


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
