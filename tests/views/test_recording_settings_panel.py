from PySide6.QtTest import QSignalSpy
from pytestqt.qtbot import QtBot

from rheed_capture.presentation.qt.panels.recording_settings import RecordingSettingsPanel


def test_recording_settings_panel_syncs_tiff_compression(qtbot: QtBot) -> None:
    """TIFF圧縮の変更通知と外部設定反映を同期する。"""
    panel = RecordingSettingsPanel()
    qtbot.addWidget(panel)
    compression_spy = QSignalSpy(panel.tiff_compression_changed)

    panel.chk_tiff_compression.setChecked(False)
    assert compression_spy.at(0) == [False]

    panel.set_tiff_compression_enabled(True)
    assert panel.chk_tiff_compression.isChecked() is True
    assert compression_spy.count() == 1
