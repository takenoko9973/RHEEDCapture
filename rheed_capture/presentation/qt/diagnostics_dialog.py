"""取得統計とRealtime処理の詳細をmodeless表示するDialog。"""

from PySide6.QtWidgets import QDialog, QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from rheed_capture.domain.acquisition_statistics import AcquisitionStatistics
from rheed_capture.presentation.qt.preview.processor import PreviewDiagnostics

DECIMAL_BYTES_PER_MEGABYTE = 1_000_000


class DiagnosticsDialog(QDialog):
    """取得、Realtime、queue/dropの詳細値を個別labelへ表示するDialog。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        """再利用可能なmodeless Diagnostics Dialogを構築する。"""
        super().__init__(parent)
        self.setWindowTitle("Diagnostics")
        self.setModal(False)
        self.setMinimumWidth(360)
        self._setup_ui()
        self._set_unavailable_values()

    def update_values(
        self,
        capture_mode: str | None,
        statistics: AcquisitionStatistics | None,
        diagnostics: PreviewDiagnostics,
    ) -> None:
        """最新snapshotをDiagnosticsの個別labelへ反映する。"""
        if statistics is None:
            acquisition_values = ("--", "--", "--", "--", "--")
            save_queue_value = "--"
        else:
            acquisition_values = (
                str(statistics.frame_count),
                _format_fps_value(statistics.current_fps),
                _format_payload_value(statistics.payload_bytes_per_second),
                f"{statistics.accumulation_progress}/{statistics.accumulation_target}",
                "Yes" if statistics.waiting_for_trigger else "No",
            )
            save_queue_value = (
                f"{statistics.save_queue_depth}/{statistics.save_queue_peak_depth}"
                if capture_mode == "recording"
                else "--"
            )

        for label, value in zip(self._acquisition_labels, acquisition_values, strict=True):
            label.setText(value)
        self.save_queue_label.setText(save_queue_value)

        self.preview_processing_display_label.setText(
            _format_processing_display(
                diagnostics.preview_processing_fps,
                diagnostics.preview_display_fps,
            )
        )
        self.graph_processing_display_label.setText(
            _format_processing_display(
                diagnostics.graph_processing_fps,
                diagnostics.graph_display_fps,
            )
        )
        self.display_refresh_label.setText(_format_refresh_rate(diagnostics.active_display_hz))
        preview_drops = (
            diagnostics.preview_input_drop_count + diagnostics.preview_result_drop_count
        )
        graph_drops = diagnostics.graph_input_drop_count + diagnostics.graph_result_drop_count
        self.drops_label.setText(f"{preview_drops}/{graph_drops}")

    def _setup_ui(self) -> None:
        """Diagnosticsの3分類と値labelを配置する。"""
        layout = QVBoxLayout(self)

        acquisition_group = QGroupBox("Acquisition")
        acquisition_layout = QFormLayout(acquisition_group)
        self.raw_frames_label = QLabel()
        self.raw_fps_label = QLabel()
        self.payload_label = QLabel()
        self.accumulation_label = QLabel()
        self.waiting_for_trigger_label = QLabel()
        self._acquisition_labels = (
            self.raw_frames_label,
            self.raw_fps_label,
            self.payload_label,
            self.accumulation_label,
            self.waiting_for_trigger_label,
        )
        acquisition_layout.addRow("Raw frames:", self.raw_frames_label)
        acquisition_layout.addRow("Raw FPS:", self.raw_fps_label)
        acquisition_layout.addRow("Payload:", self.payload_label)
        acquisition_layout.addRow("Accumulation:", self.accumulation_label)
        acquisition_layout.addRow("Waiting for trigger:", self.waiting_for_trigger_label)
        layout.addWidget(acquisition_group)

        realtime_group = QGroupBox("Realtime")
        realtime_layout = QFormLayout(realtime_group)
        self.preview_processing_display_label = QLabel()
        self.graph_processing_display_label = QLabel()
        self.display_refresh_label = QLabel()
        realtime_layout.addRow(
            "Preview processing/display:",
            self.preview_processing_display_label,
        )
        realtime_layout.addRow(
            "Graph processing/display:",
            self.graph_processing_display_label,
        )
        realtime_layout.addRow("Display refresh:", self.display_refresh_label)
        layout.addWidget(realtime_group)

        queue_group = QGroupBox("Queues / Drops")
        queue_layout = QFormLayout(queue_group)
        self.drops_label = QLabel()
        self.save_queue_label = QLabel()
        queue_layout.addRow("Preview/Graph drops:", self.drops_label)
        queue_layout.addRow("Save queue current/peak:", self.save_queue_label)
        layout.addWidget(queue_group)

    def _set_unavailable_values(self) -> None:
        """snapshotが未提供の初期表示を`--`へ揃える。"""
        for label in self._acquisition_labels:
            label.setText("--")
        self.preview_processing_display_label.setText("--")
        self.graph_processing_display_label.setText("--")
        self.display_refresh_label.setText("--")
        self.drops_label.setText("--")
        self.save_queue_label.setText("--")


def _format_fps_value(value: float | None) -> str:
    """FPSを単位付きで表示し、未定義値は`--`へ変換する。"""
    return "--" if value is None else f"{value:.1f} fps"


def _format_payload_value(payload_bytes_per_second: float | None) -> str:
    """転送量を10進MB/sへ変換し、未定義値は`--`へ変換する。"""
    if payload_bytes_per_second is None:
        return "--"
    return f"{payload_bytes_per_second / DECIMAL_BYTES_PER_MEGABYTE:.1f} MB/s"


def _format_processing_display(processing_fps: float, display_fps: float) -> str:
    """処理FPSと表示FPSをDiagnostics用の1値へ整形する。"""
    return f"{processing_fps:.1f}/{display_fps:.1f} fps"


def _format_refresh_rate(refresh_rate_hz: float) -> str:
    """表示refresh rateを単位付きで整形し、無効値は`--`へ変換する。"""
    return "--" if refresh_rate_hz <= 0 else f"{refresh_rate_hz:.1f} Hz"
