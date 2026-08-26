from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QLabel

if TYPE_CHECKING:
    from rheed_capture.infrastructure.config.schema import RecordingCaptureSettings


TIFF_COMPRESSION_TOOLTIP = (
    "TIFF保存時のzlib圧縮を切り替えます。"
    "OFFは容量が増える代わり保存負荷が下がり、高frame-rate Recordingで有効です。"
)


class RecordingSettingsPanel(QGroupBox):
    """SettingsタブでRecordingの保存方式を編集する小さなパネル。"""

    tiff_compression_changed = Signal(bool)

    def __init__(self) -> None:
        """Recording保存設定の入力Widgetを生成する。"""
        super().__init__("Recording Settings")
        self._setup_ui()

    def _setup_ui(self) -> None:
        """TIFF圧縮の表示、Tooltip、Signal接続を設定する。"""
        layout = QFormLayout(self)

        self.lbl_tiff_compression = QLabel("TIFF Compression:")
        self.chk_tiff_compression = QCheckBox("On")
        self.chk_tiff_compression.setChecked(True)
        self.lbl_tiff_compression.setToolTip(TIFF_COMPRESSION_TOOLTIP)
        self.chk_tiff_compression.setToolTip(TIFF_COMPRESSION_TOOLTIP)
        layout.addRow(self.lbl_tiff_compression, self.chk_tiff_compression)

        self.chk_tiff_compression.toggled.connect(self.tiff_compression_changed.emit)

    def set_tiff_compression_enabled(self, enabled: bool) -> None:
        """保存済みTIFF圧縮設定をcheckboxへ反映する。"""
        with QSignalBlocker(self.chk_tiff_compression):
            self.chk_tiff_compression.setChecked(enabled)

    def apply_settings(self, settings: RecordingCaptureSettings) -> None:
        """保存済みRecording設定からTIFF圧縮状態を読み込む。"""
        self.set_tiff_compression_enabled(settings.tiff_compression_enabled)
