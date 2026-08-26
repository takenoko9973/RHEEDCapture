from pytestqt.qtbot import QtBot

from rheed_capture.domain.acquisition_statistics import AcquisitionStatistics
from rheed_capture.presentation.qt.diagnostics_dialog import DiagnosticsDialog
from rheed_capture.presentation.qt.preview.processor import PreviewDiagnostics


def _make_diagnostics() -> PreviewDiagnostics:
    """Diagnostics表示テスト用の固定snapshotを作る。"""
    return PreviewDiagnostics(
        preview_processing_fps=12.3,
        graph_processing_fps=23.4,
        preview_display_fps=45.6,
        graph_display_fps=56.7,
        active_display_hz=60.0,
        preview_processed_frames=100,
        graph_processed_frames=100,
        preview_display_frames=90,
        graph_display_frames=90,
        preview_input_drop_count=2,
        graph_input_drop_count=1,
        preview_result_drop_count=1,
        graph_result_drop_count=3,
    )


def test_diagnostics_dialog_renders_values_in_individual_labels(qtbot: QtBot) -> None:
    """Acquisition、Realtime、queue/dropを個別の値labelへ表示する。"""
    dialog = DiagnosticsDialog()
    qtbot.addWidget(dialog)
    statistics = AcquisitionStatistics(
        current_fps=138.44,
        average_fps=136.86,
        frame_count=100,
        payload_bytes_per_second=80_650_000.0,
        accumulation_progress=2,
        accumulation_target=4,
        waiting_for_trigger=True,
        save_queue_depth=12,
        save_queue_peak_depth=34,
    )

    dialog.update_values("recording", statistics, _make_diagnostics())

    assert dialog.raw_frames_label.text() == "100"
    assert dialog.raw_fps_label.text() == "138.4 fps"
    assert dialog.payload_label.text() == "80.7 MB/s"
    assert dialog.accumulation_label.text() == "2/4"
    assert dialog.waiting_for_trigger_label.text() == "Yes"
    assert dialog.preview_processing_display_label.text() == "12.3/45.6 fps"
    assert dialog.graph_processing_display_label.text() == "23.4/56.7 fps"
    assert dialog.display_refresh_label.text() == "60.0 Hz"
    assert dialog.drops_label.text() == "3/4"
    assert dialog.save_queue_label.text() == "12/34"


def test_diagnostics_dialog_marks_unavailable_mode_values_as_missing(qtbot: QtBot) -> None:
    """有限撮影など統計snapshotがないmodeでは該当値を`--`にする。"""
    dialog = DiagnosticsDialog()
    qtbot.addWidget(dialog)

    dialog.update_values("sequence", None, _make_diagnostics())

    assert dialog.raw_frames_label.text() == "--"
    assert dialog.raw_fps_label.text() == "--"
    assert dialog.payload_label.text() == "--"
    assert dialog.accumulation_label.text() == "--"
    assert dialog.waiting_for_trigger_label.text() == "--"
    assert dialog.save_queue_label.text() == "--"
    assert dialog.preview_processing_display_label.text() == "12.3/45.6 fps"
    assert dialog.graph_processing_display_label.text() == "23.4/56.7 fps"
    assert dialog.display_refresh_label.text() == "60.0 Hz"
    assert dialog.drops_label.text() == "3/4"
