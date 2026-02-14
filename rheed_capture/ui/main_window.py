import logging

import numpy as np
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rheed_capture.core.camera_device import CameraDevice
from rheed_capture.core.capture_service import CaptureService
from rheed_capture.core.preview_worker import PreviewWorker
from rheed_capture.core.storage import ExperimentStorage

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, camera: CameraDevice, storage: ExperimentStorage):
        super().__init__()
        self.camera = camera
        self.storage = storage
        self.capture_service = None

        self.setWindowTitle("RHEED Capture System")
        self.resize(1000, 700)

        self._setup_ui()
        self._start_preview()

    def _setup_ui(self) -> None:
        """UIコンポーネントの構築"""
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # --- 左側: 画像プレビュー領域 ---
        self.image_label = QLabel("Camera not connected")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background-color: black; color: white;")
        self.image_label.setMinimumSize(640, 480)
        main_layout.addWidget(self.image_label, stretch=2)

        # --- 右側: コントロールパネル領域 ---
        control_layout = QVBoxLayout()
        control_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 1. プレビュー設定グループ
        group_preview = QGroupBox("Preview Settings")
        form_preview = QFormLayout()

        self.spin_preview_exp = QDoubleSpinBox()
        self.spin_preview_exp.setRange(0.1, 10000.0)
        self.spin_preview_exp.setValue(10.0)
        self.spin_preview_exp.setSuffix(" ms")
        self.spin_preview_exp.valueChanged.connect(self._on_preview_exp_changed)

        self.spin_preview_gain = QDoubleSpinBox()
        self.spin_preview_gain.setRange(0.0, 24.0)
        self.spin_preview_gain.setValue(0.0)
        self.spin_preview_gain.valueChanged.connect(self._on_preview_gain_changed)

        self.chk_processing = QCheckBox("Enable CLAHE Processing")
        self.chk_processing.toggled.connect(self._on_processing_toggled)

        form_preview.addRow("Exposure:", self.spin_preview_exp)
        form_preview.addRow("Gain:", self.spin_preview_gain)
        form_preview.addRow("", self.chk_processing)
        group_preview.setLayout(form_preview)
        control_layout.addWidget(group_preview)

        # 2. 自動撮影シーケンスグループ
        group_seq = QGroupBox("Sequence Capture")
        form_seq = QFormLayout()

        self.edit_seq_exp = QLineEdit("10, 50, 100")
        self.edit_seq_gain = QLineEdit("0")
        self.btn_start_seq = QPushButton("Start Sequence Capture")
        self.btn_start_seq.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;")
        self.btn_start_seq.clicked.connect(self._on_start_sequence)

        self.btn_cancel_seq = QPushButton("Cancel")
        self.btn_cancel_seq.setEnabled(False)
        self.btn_cancel_seq.clicked.connect(self._on_cancel_sequence)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        form_seq.addRow("Exposures (ms):", self.edit_seq_exp)
        form_seq.addRow("Gains:", self.edit_seq_gain)
        form_seq.addRow(self.btn_start_seq)
        form_seq.addRow(self.btn_cancel_seq)
        form_seq.addRow(self.progress_bar)
        group_seq.setLayout(form_seq)
        control_layout.addWidget(group_seq)

        main_layout.addLayout(control_layout, stretch=1)

    def _start_preview(self) -> None:
        """プレビュースレッドの初期化と開始"""
        self.preview_worker = PreviewWorker(self.camera)
        self.preview_worker.image_ready.connect(self._update_image_label)
        self.preview_worker.error_occurred.connect(self._show_error)

        # 初期パラメータをカメラに適用
        self._on_preview_exp_changed(self.spin_preview_exp.value())
        self._on_preview_gain_changed(self.spin_preview_gain.value())

        self.camera.start_preview_grab()
        self.preview_worker.start()

    @Slot(float)
    def _on_preview_exp_changed(self, value) -> None:
        self.camera.set_exposure(value)

    @Slot(float)
    def _on_preview_gain_changed(self, value) -> None:
        self.camera.set_gain(value)

    @Slot(bool)
    def _on_processing_toggled(self, checked) -> None:
        self.preview_worker.set_processing_enabled(checked)

    @Slot(np.ndarray)
    def _update_image_label(self, image_data: np.ndarray) -> None:
        """Workerから受け取った8bit画像をQLabelに描画する"""
        height, width = image_data.shape
        bytes_per_line = width

        # 参照を維持するためにQImageを生成 (Grayscale8フォーマット)
        q_image = QImage(
            image_data.data, width, height, bytes_per_line, QImage.Format.Format_Grayscale8
        )

        # QLabelのサイズに合わせて縮小表示 (アスペクト比維持)
        pixmap = QPixmap.fromImage(q_image)
        scaled_pixmap = pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled_pixmap)

    def _parse_sequence_inputs(self) -> tuple[list[float], list[float]]:
        """カンマ区切りの文字列をfloatのリストに変換"""
        try:
            exp_list = [float(x.strip()) for x in self.edit_seq_exp.text().split(",") if x.strip()]
            gain_list = [
                float(x.strip()) for x in self.edit_seq_gain.text().split(",") if x.strip()
            ]
            if not exp_list or not gain_list:
                msg = "List cannot be empty."
                raise ValueError(msg)

            return exp_list, gain_list
        except ValueError:
            QMessageBox.warning(
                self,
                "Input Error",
                "Invalid input for Exposure or Gain lists. Please enter numbers separated by commas.",
            )
            return [], []

    @Slot()
    def _on_start_sequence(self) -> None:
        exp_list, gain_list = self._parse_sequence_inputs()
        if not exp_list or not gain_list:
            return

        # UIの無効化
        self.btn_start_seq.setEnabled(False)
        self.btn_cancel_seq.setEnabled(True)
        self.group_preview_state(False)
        self.progress_bar.setValue(0)

        # CaptureServiceの初期化と開始
        self.capture_service = CaptureService(self.camera, self.storage, exp_list, gain_list)
        self.capture_service.progress_update.connect(self._update_progress)
        self.capture_service.sequence_finished.connect(self._on_sequence_finished)
        self.capture_service.error_occurred.connect(self._show_error)
        self.capture_service.start()

    @Slot()
    def _on_cancel_sequence(self) -> None:
        if self.capture_service and self.capture_service.isRunning():
            self.capture_service.cancel()
            self.btn_cancel_seq.setEnabled(False)

    @Slot(int, int)
    def _update_progress(self, current, total) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    @Slot(bool)
    def _on_sequence_finished(self, success) -> None:
        # UIの有効化
        self.btn_start_seq.setEnabled(True)
        self.btn_cancel_seq.setEnabled(False)
        self.group_preview_state(True)

        if success:
            QMessageBox.information(
                self, "Sequence Complete", "All images have been captured successfully."
            )

    def group_preview_state(self, enabled: bool) -> None:
        """撮影中はプレビュー設定を変更できないようにする"""
        self.spin_preview_exp.setEnabled(enabled)
        self.spin_preview_gain.setEnabled(enabled)

    @Slot(str)
    def _show_error(self, message) -> None:
        QMessageBox.critical(self, "Error", message)

    def closeEvent(self, event) -> None:  # noqa: N802
        """ウィンドウを閉じる際の安全な終了処理"""
        if self.capture_service and self.capture_service.isRunning():
            QMessageBox.warning(self, "Warning", "Cannot close while capturing.")
            event.ignore()
            return

        if hasattr(self, "preview_worker"):
            self.preview_worker.stop()
            self.preview_worker.wait(2000)

        self.camera.disconnect()
        event.accept()
