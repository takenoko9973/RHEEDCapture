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
        # 単位は項目名側だけに出し、チップ表示には含めない。
        layout.addRow("Exposure (ms):", self.edit_exposure_values)
        layout.addRow("Gain:", self.edit_gain_values)

        self.edit_exposure_values.editingFinished.connect(self._on_exposure_edited)
        self.edit_gain_values.editingFinished.connect(self._on_gain_edited)

    def set_values(self, exposure_ms_values: list[float], gain_values: list[int]) -> None:
        """保存済み設定または外部更新を、編集欄と内部状態へ同期する。"""
        self._exposure_ms_values = list(exposure_ms_values)
        self._gain_values = list(gain_values)
        self._sync_text()

    def exposure_ms_values(self) -> list[float]:
        """保存時に呼び出すため、内部リストのコピーを返す。"""
        return list(self._exposure_ms_values)

    def gain_values(self) -> list[int]:
        """保存時に呼び出すため、内部リストのコピーを返す。"""
        return list(self._gain_values)

    @Slot()
    def _on_exposure_edited(self) -> None:
        try:
            values = parse_numbers(self.edit_exposure_values.text(), float)
            if not values:
                self._empty_list_error()
        except ValueError:
            # 不正入力時は状態を更新せず、保持している正しい値をUIへ戻す。
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
            # ゲインはカメラへ渡す整数値なので、候補値もintで正規化する。
            values = parse_numbers(self.edit_gain_values.text(), int)
            if not values:
                self._empty_list_error()
        except ValueError:
            # "G5" のような接頭辞付き入力はここで弾かれ、直前の正しい表示に戻る。
            self.error_occurred.emit(
                "ゲインの形式が正しくありません。\nカンマ区切りの整数を入力してください。"
            )
            self._sync_text()
            return

        self._gain_values = values
        self._sync_text()
        self.gain_values_changed.emit(self.gain_values())

    def _sync_text(self) -> None:
        """内部状態をQLineEditへ戻す。"""
        self.edit_exposure_values.setText(self._format_values(self._exposure_ms_values))
        self.edit_gain_values.setText(self._format_values(self._gain_values))

    @staticmethod
    def _format_values(values: list[float] | list[int]) -> str:
        """チップと同じく数値だけを表示するため、不要な`.0`は落とす。"""
        return ", ".join(f"{value:g}" for value in values)

    def _empty_list_error(self) -> None:
        msg = "リストが空です"
        raise ValueError(msg)
