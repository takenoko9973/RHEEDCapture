import numpy as np
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox, QSlider


class PreviewPanel(QGroupBox):
    exposure_changed = Signal(float)
    gain_changed = Signal(float)

    clahe_toggled = Signal(bool)

    def __init__(self, exp_bounds: tuple[float, float], gain_bounds: tuple[float, float]) -> None:
        super().__init__("Preview Settings")
        self._setup_ui(exp_bounds, gain_bounds)

    def _setup_ui(self, exp_bounds: tuple[float, float], gain_bounds: tuple[float, float]) -> None:
        layout = QFormLayout(self)
        exp_min, exp_max = exp_bounds
        gain_min, gain_max = gain_bounds

        # 露光時間UI
        self.spin_expo = QDoubleSpinBox(value=1, minimum=exp_min, maximum=exp_max)
        self.spin_expo.setSuffix(" ms")
        self.slider_expo = QSlider(Qt.Orientation.Horizontal)
        self.slider_expo.setValue(50000)
        self.slider_expo.setRange(int(np.ceil(exp_min * 100)), int(exp_max * 100))

        # ゲインUI
        self.spin_gain = QDoubleSpinBox(minimum=gain_min, maximum=gain_max)
        self.slider_gain = QSlider(Qt.Orientation.Horizontal)
        self.slider_gain.setRange(int(gain_min * 100), int(gain_max * 100))

        self.chk_processing = QCheckBox("Enable CLAHE Processing")

        layout.addRow("Exposure:", self.spin_expo)
        layout.addRow("", self.slider_expo)
        layout.addRow("Gain:", self.spin_gain)
        layout.addRow("", self.slider_gain)
        layout.addRow("", self.chk_processing)

        # 内部の双方向同期シグナル結線
        self.spin_expo.valueChanged.connect(self._on_spin_exp_changed)
        self.slider_expo.valueChanged.connect(self._on_slider_exp_changed)
        self.spin_gain.valueChanged.connect(self._on_spin_gain_changed)
        self.slider_gain.valueChanged.connect(self._on_slider_gain_changed)

        # 外部へのシグナル発信
        self.chk_processing.toggled.connect(self.clahe_toggled.emit)

    # --- 内部の同期ロジック ---
    @Slot(float)
    def _on_spin_exp_changed(self, value: float) -> None:
        self.slider_expo.blockSignals(True)
        self.slider_expo.setValue(int(value * 100))
        self.slider_expo.blockSignals(False)
        self.exposure_changed.emit(value)  # MainWindowへ通知

    @Slot(int)
    def _on_slider_exp_changed(self, value: int) -> None:
        float_val = value / 100.0
        self.spin_expo.blockSignals(True)
        self.spin_expo.setValue(float_val)
        self.spin_expo.blockSignals(False)
        self.exposure_changed.emit(float_val)  # MainWindowへ通知

    @Slot(float)
    def _on_spin_gain_changed(self, value: float) -> None:
        self.slider_gain.blockSignals(True)
        self.slider_gain.setValue(value)
        self.slider_gain.blockSignals(False)
        self.gain_changed.emit(value)

    @Slot(int)
    def _on_slider_gain_changed(self, value: int) -> None:
        self.spin_gain.blockSignals(True)
        self.spin_gain.setValue(value)
        self.spin_gain.blockSignals(False)
        self.gain_changed.emit(value)

    # --- 外部からのデータ設定/取得用メソッド ---
    def set_values(self, exp: float, gain: float, clahe: bool) -> None:
        self.spin_expo.setValue(exp)
        self.spin_gain.setValue(gain)
        self.chk_processing.setChecked(clahe)

    def get_values(self) -> dict:
        return {
            "preview_expo": self.spin_expo.value(),
            "preview_gain": self.spin_gain.value(),
            "enable_clahe": self.chk_processing.isChecked(),
        }

    def set_controls_enabled(self, enabled: bool) -> None:
        self.spin_expo.setEnabled(enabled)
        self.slider_expo.setEnabled(enabled)
        self.spin_gain.setEnabled(enabled)
        self.slider_gain.setEnabled(enabled)
