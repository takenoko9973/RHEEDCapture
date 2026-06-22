from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLineEdit

from rheed_capture.utils import parse_numbers


class CaptureChipsPanel(QGroupBox):
    """Settingsタブで撮影条件チップ候補をコンマ区切り入力で編集する。"""

    exposure_values_changed = Signal(list)
    gain_values_changed = Signal(list)
    error_occurred = Signal(str)

    def __init__(self) -> None:
        super().__init__("Capture Condition Chips")
        self._exposure_ms_values: list[float] = []
        self._gain_values: list[int] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QFormLayout(self)
        self.edit_exposure_values = QLineEdit()
        self.edit_gain_values = QLineEdit()
        layout.addRow("Exposure (ms):", self.edit_exposure_values)
        layout.addRow("Gain:", self.edit_gain_values)

        self.edit_exposure_values.editingFinished.connect(self._on_exposure_edited)
        self.edit_gain_values.editingFinished.connect(self._on_gain_edited)

    def set_values(self, exposure_ms_values: list[float], gain_values: list[int]) -> None:
        self._exposure_ms_values = list(exposure_ms_values)
        self._gain_values = list(gain_values)
        self._sync_text()

    def exposure_ms_values(self) -> list[float]:
        return list(self._exposure_ms_values)

    def gain_values(self) -> list[int]:
        return list(self._gain_values)

    @Slot()
    def _on_exposure_edited(self) -> None:
        try:
            values = parse_numbers(self.edit_exposure_values.text(), float)
            if not values:
                self._empty_list_error()
        except ValueError:
            self.error_occurred.emit(
                "露光時間の形式が正しくありません。\nカンマ区切りの数値を入力してください。"
            )
            self._sync_text()
            return

        self._exposure_ms_values = values
        self._sync_text()
        self.exposure_values_changed.emit(self.exposure_ms_values())

    @Slot()
    def _on_gain_edited(self) -> None:
        try:
            values = parse_numbers(self.edit_gain_values.text(), int)
            if not values:
                self._empty_list_error()
        except ValueError:
            self.error_occurred.emit(
                "ゲインの形式が正しくありません。\nカンマ区切りの整数を入力してください。"
            )
            self._sync_text()
            return

        self._gain_values = values
        self._sync_text()
        self.gain_values_changed.emit(self.gain_values())

    def _sync_text(self) -> None:
        self.edit_exposure_values.setText(self._format_values(self._exposure_ms_values))
        self.edit_gain_values.setText(self._format_values(self._gain_values))

    @staticmethod
    def _format_values(values: list[float] | list[int]) -> str:
        return ", ".join(f"{value:g}" for value in values)

    def _empty_list_error(self) -> None:
        msg = "リストが空です"
        raise ValueError(msg)
