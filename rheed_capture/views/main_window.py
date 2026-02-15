import logging

import numpy as np
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from rheed_capture.models.hardware.camera_device import CameraDevice
from rheed_capture.models.io.settings import AppSettings
from rheed_capture.models.io.storage import ExperimentStorage
from rheed_capture.viewmodels.capture_service import CaptureService
from rheed_capture.viewmodels.preview_worker import PreviewWorker

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, camera: CameraDevice, storage: ExperimentStorage) -> None:
        super().__init__()
        self.camera = camera
        self.storage = storage
        self.capture_service = None

        self.setWindowTitle("RHEED Capture System")
        self.resize(1000, 700)

        self._setup_ui()
        self._start_preview()
        self._load_settings()

    def _setup_ui(self) -> None:
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # --- 画像表示部 ---
        self.image_label = QLabel("Camera not connected")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background-color: black; color: white;")
        main_layout.addWidget(self.image_label, stretch=2)

        # --- コントロール部 ---
        control_layout = QVBoxLayout()
        control_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 0. 保存先設定グループ (NEW)
        group_storage = QGroupBox("Storage Settings")
        storage_layout = QVBoxLayout()

        # ルートフォルダ選択
        root_h_layout = QHBoxLayout()
        self.lbl_root_dir = QLabel(str(self.storage.root_dir))
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._on_browse_root)
        root_h_layout.addWidget(self.lbl_root_dir)
        root_h_layout.addWidget(btn_browse)

        # 現在のターゲットフォルダ表示とブランチ更新
        target_h_layout = QHBoxLayout()
        self.lbl_target_dir = QLabel(f"Target: {self.storage.get_current_experiment_dir().name}")
        self.lbl_target_dir.setStyleSheet("font-weight: bold; color: blue;")
        btn_new_branch = QPushButton("New Branch (-n)")
        btn_new_branch.clicked.connect(self._on_new_branch)
        target_h_layout.addWidget(self.lbl_target_dir)
        target_h_layout.addWidget(btn_new_branch)

        storage_layout.addLayout(root_h_layout)
        storage_layout.addLayout(target_h_layout)
        group_storage.setLayout(storage_layout)
        control_layout.addWidget(group_storage)

        # 1. プレビュー設定グループ (Slider連携追加)
        group_preview = QGroupBox("Preview Settings")
        form_preview = QFormLayout()

        # --- 露光時間 (SpinBox + Slider) ---
        exp_min, exp_max = self.camera.get_exposure_bounds()
        self.spin_preview_exp = QDoubleSpinBox(value=1, minimum=exp_min, maximum=exp_max)
        self.spin_preview_exp.setRange(exp_min, exp_max)
        self.spin_preview_exp.setSuffix(" ms")

        self.slider_exp = QSlider(Qt.Orientation.Horizontal)
        self.slider_exp.setValue(1)
        # QSliderは整数のみなので、値を1000倍して扱う (精度0.001ms)
        self.slider_exp.setRange(np.ceil(exp_min * 100), int(exp_max * 100))

        # シグナル連携
        self.spin_preview_exp.valueChanged.connect(self._on_preview_exp_spin_changed)
        self.slider_exp.valueChanged.connect(self._on_preview_exp_slider_changed)

        # --- ゲイン (SpinBox + Slider) ---
        gain_min, gain_max = self.camera.get_gain_bounds()
        self.spin_preview_gain = QDoubleSpinBox()
        self.spin_preview_gain.setRange(gain_min, gain_max)

        self.slider_gain = QSlider(Qt.Orientation.Horizontal)
        self.slider_gain.setRange(int(gain_min * 100), int(gain_max * 100))

        # シグナル連携
        self.spin_preview_gain.valueChanged.connect(self._on_preview_gain_spin_changed)
        self.slider_gain.valueChanged.connect(self._on_preview_gain_slider_changed)

        self.chk_processing = QCheckBox("Enable CLAHE Processing")
        self.chk_processing.toggled.connect(self._on_processing_toggled)

        form_preview.addRow("Exposure:", self.spin_preview_exp)
        form_preview.addRow("", self.slider_exp)
        form_preview.addRow("Gain:", self.spin_preview_gain)
        form_preview.addRow("", self.slider_gain)
        form_preview.addRow("", self.chk_processing)
        group_preview.setLayout(form_preview)
        control_layout.addWidget(group_preview)

        # 2. シーケンス撮影グループ (変更なし)
        group_seq = QGroupBox("Sequence Capture")
        form_seq = QFormLayout()
        self.edit_seq_exp = QLineEdit("10, 50, 100")
        self.edit_seq_gain = QLineEdit("0")
        self.btn_start_seq = QPushButton("Start Sequence Capture")
        self.btn_start_seq.clicked.connect(self._on_start_sequence)
        self.btn_cancel_seq = QPushButton("Cancel")
        self.btn_cancel_seq.setEnabled(False)
        self.btn_cancel_seq.clicked.connect(self._on_cancel_sequence)
        self.progress_bar = QProgressBar()

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

        self.preview_worker.start()

    @Slot()
    def _on_browse_root(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Root Directory", str(self.storage.root_dir)
        )
        if dir_path:
            self.storage.set_root_dir(dir_path)
            self.lbl_root_dir.setText(dir_path)
            self._update_target_dir_label()

    @Slot()
    def _on_new_branch(self) -> None:
        new_name = self.storage.increment_branch()
        self._update_target_dir_label()
        QMessageBox.information(
            self, "Branch Updated", f"Next capture will be saved in:\n{new_name}"
        )

    def _update_target_dir_label(self) -> None:
        self.lbl_target_dir.setText(f"Target: {self.storage.get_current_experiment_dir().name}")

    # --- スライダーとスピンボックスの双方向同期 ---
    @Slot(float)
    def _on_preview_exp_spin_changed(self, value) -> None:
        self.slider_exp.blockSignals(True)
        self.slider_exp.setValue(int(value * 100))
        self.slider_exp.blockSignals(False)
        self.camera.set_exposure(value)

    @Slot(int)
    def _on_preview_exp_slider_changed(self, value) -> None:
        self.spin_preview_exp.blockSignals(True)
        self.spin_preview_exp.setValue(value / 100.0)
        self.spin_preview_exp.blockSignals(False)
        self.camera.set_exposure(value / 100.0)

    @Slot(float)
    def _on_preview_gain_spin_changed(self, value) -> None:
        self.slider_gain.blockSignals(True)
        self.slider_gain.setValue(int(value * 100))
        self.slider_gain.blockSignals(False)
        self.camera.set_gain(value)

    @Slot(int)
    def _on_preview_gain_slider_changed(self, value) -> None:
        self.spin_preview_gain.blockSignals(True)
        self.spin_preview_gain.setValue(value / 100.0)
        self.spin_preview_gain.blockSignals(False)
        self.camera.set_gain(value / 100.0)

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

        # プレビューを一時停止
        self.preview_worker.preview_paused.connect(
            self._start_capture_service_after_pause, Qt.SingleShotConnection
        )
        self.preview_worker.request_pause()

    @Slot()
    def _start_capture_service_after_pause(self) -> None:
        """PreviewWorkerの安全な停止が確認された後に自動で呼ばれる"""
        exp_list, gain_list = self._parse_sequence_inputs()

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

        # プレビュー再開
        self.preview_worker.resume()

        if success:
            QMessageBox.information(self, "Sequence Complete", "撮影が完了しました。")

    def group_preview_state(self, enabled: bool) -> None:
        """撮影中はプレビュー設定を変更できないようにする"""
        self.spin_preview_exp.setEnabled(enabled)
        self.spin_preview_gain.setEnabled(enabled)

    @Slot(str)
    def _show_error(self, message) -> None:
        QMessageBox.critical(self, "Error", message)

    def _load_settings(self):
        settings = AppSettings.load()
        if not settings:
            return

        if "root_dir" in settings:
            self.storage.set_root_dir(settings["root_dir"])
            self.lbl_root_dir.setText(settings["root_dir"])
            self._update_target_dir_label()

        if "preview_exp" in settings:
            self.spin_preview_exp.setValue(settings["preview_exp"])
        if "preview_gain" in settings:
            self.spin_preview_gain.setValue(settings["preview_gain"])
        if "seq_exp_list" in settings:
            self.edit_seq_exp.setText(settings["seq_exp_list"])
        if "seq_gain_list" in settings:
            self.edit_seq_gain.setText(settings["seq_gain_list"])
        if "enable_clahe" in settings:
            self.chk_processing.setChecked(settings["enable_clahe"])

    def closeEvent(self, event) -> None:
        if self.capture_service and self.capture_service.isRunning():
            QMessageBox.warning(self, "Warning", "Cannot close while capturing.")
            event.ignore()
            return

        # 終了前に設定を保存
        settings_to_save = {
            "root_dir": str(self.storage.root_dir),
            "preview_exp": self.spin_preview_exp.value(),
            "preview_gain": self.spin_preview_gain.value(),
            "seq_exp_list": self.edit_seq_exp.text(),
            "seq_gain_list": self.edit_seq_gain.text(),
            "enable_clahe": self.chk_processing.isChecked(),
        }
        AppSettings.save(settings_to_save)

        if hasattr(self, "preview_worker"):
            self.preview_worker.stop()
            self.preview_worker.wait(2000)

        self.camera.disconnect()
        event.accept()
