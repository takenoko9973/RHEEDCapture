import math

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox, QSlider, QSpinBox


class PreviewPanel(QGroupBox):
    exposure_changed = Signal(float)
    gain_changed = Signal(int)

    clahe_toggled = Signal(bool)

    expo_steps = 1000  # 対数スライドの解像度

    def __init__(self, expo_bounds: tuple[float, float], gain_bounds: tuple[int, int]) -> None:
        super().__init__("Preview Settings")
        self._setup_ui(expo_bounds, gain_bounds)

    def _setup_ui(self, expo_bounds: tuple[float, float], gain_bounds: tuple[int, int]) -> None:
        layout = QFormLayout(self)
        self.expo_min, self.expo_max = expo_bounds
        self.gain_min, self.gain_max = gain_bounds

        self.expo_min = max(self.expo_min, 0.01)  # 小数点第2まで表示するため、最小値を調整

        # === 露光時間UI (対数スケール)
        self.spin_expo = QDoubleSpinBox()
        self.spin_expo.setRange(self.expo_min, self.expo_max)
        self.spin_expo.setSuffix(" ms")
        # タイピング中は値を更新せず、Enterキー押下かフォーカス外れ時のみ更新する
        self.spin_expo.setKeyboardTracking(False)

        self.slider_expo = QSlider(Qt.Orientation.Horizontal)
        self.slider_expo.setRange(0, self.expo_steps)

        # === ゲインUI
        self.spin_gain = QSpinBox()
        self.spin_gain.setRange(self.gain_min, self.gain_max)
        self.spin_gain.setKeyboardTracking(False)

        self.slider_gain = QSlider(Qt.Orientation.Horizontal)
        self.slider_gain.setRange(self.gain_min, self.gain_max)

        self.chk_processing = QCheckBox("Enable CLAHE Processing")

        layout.addRow("Exposure:", self.spin_expo)
        layout.addRow("", self.slider_expo)
        layout.addRow("Gain:", self.spin_gain)
        layout.addRow("", self.slider_gain)
        layout.addRow("", self.chk_processing)

        # 内部の双方向同期シグナル結線
        # SpinBox: 直接入力時は即座に反映
        self.spin_expo.valueChanged.connect(self._on_spin_expo_changed)
        self.spin_gain.valueChanged.connect(self._on_spin_gain_changed)

        # Slider: 動かしている最中 (valueChanged) は UI上のSpinBoxだけを更新させる
        self.slider_expo.valueChanged.connect(self._on_slider_expo_changed)
        self.slider_gain.valueChanged.connect(self._on_slider_gain_changed)

        # Slider: マウスを離した瞬間 (sliderReleased) に初めてカメラに値を送る
        self.slider_expo.sliderReleased.connect(self._on_slider_expo_released)
        self.slider_gain.sliderReleased.connect(self._on_slider_gain_released)

        # 外部へのシグナル発信
        self.chk_processing.toggled.connect(self.clahe_toggled.emit)

    # ==========================================
    # 対数変換ヘルパーメソッド
    # ==========================================
    def _expo_to_slider(self, expo_val: float) -> int:
        """実際の露光時間からスライダーの段階(0~1000)を計算"""
        if expo_val <= self.expo_min:
            return 0
        if expo_val >= self.expo_max:
            return self.expo_steps

        log_min = math.log10(self.expo_min)
        log_max = math.log10(self.expo_max)
        log_val = math.log10(expo_val)

        t = (log_val - log_min) / (log_max - log_min)
        return round(t * self.expo_steps)

    def _slider_to_expo(self, slider_val: int) -> float:
        """スライダーの段階(0~1000)から実際の露光時間(対数)を計算"""
        if slider_val <= 0:
            return self.expo_min
        if slider_val >= self.expo_steps:
            return self.expo_max

        log_min = math.log10(self.expo_min)
        log_max = math.log10(self.expo_max)
        t = slider_val / self.expo_steps

        log_val = log_min + t * (log_max - log_min)
        return 10**log_val

    # ==========================================
    # 同期・イベントハンドラ
    # ==========================================

    # --- Exposure ---
    @Slot(float)
    def _on_spin_expo_changed(self, value: float) -> None:
        self.slider_expo.blockSignals(True)
        self.slider_expo.setValue(self._expo_to_slider(value))
        self.slider_expo.blockSignals(False)
        self.exposure_changed.emit(value)  # SpinBoxからの直接入力は即カメラへ送る

    @Slot(int)
    def _on_slider_expo_changed(self, value: int) -> None:
        """露光時間 ドラッグ中: スピンボックスの見た目だけを更新し、カメラへは送らない"""
        float_val = self._slider_to_expo(value)
        self.spin_expo.blockSignals(True)
        self.spin_expo.setValue(float_val)
        self.spin_expo.blockSignals(False)

    @Slot()
    def _on_slider_expo_released(self) -> None:
        """露光時間 ドラッグ終了時: ここで初めてカメラへ値を送る"""
        self.exposure_changed.emit(self.spin_expo.value())

    # --- Gain ---
    @Slot(float)
    def _on_spin_gain_changed(self, value: int) -> None:
        self.slider_gain.blockSignals(True)
        self.slider_gain.setValue(value)
        self.slider_gain.blockSignals(False)
        self.gain_changed.emit(value)

    @Slot(int)
    def _on_slider_gain_changed(self, value: int) -> None:
        """ゲイン ドラッグ中: スピンボックスの見た目だけを更新し、カメラへは送らない"""
        self.spin_gain.blockSignals(True)
        self.spin_gain.setValue(value)
        self.spin_gain.blockSignals(False)

    @Slot()
    def _on_slider_gain_released(self) -> None:
        """ゲイン ドラッグ終了時: ここで初めてカメラへ値を送る"""
        self.gain_changed.emit(self.spin_gain.value())

    # --- 外部からのデータ設定/取得用メソッド ---
    def set_values(self, expo: float, gain: float, clahe: bool) -> None:
        self.spin_expo.setValue(expo)
        self.spin_gain.setValue(int(gain))
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
