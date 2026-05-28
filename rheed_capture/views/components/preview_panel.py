import math

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QSlider,
    QSpinBox,
    QWidget,
)

from rheed_capture.utils import round_sig_figs
from rheed_capture.views.grid_spec import (
    DEFAULT_GRID_SHAPE,
    DEFAULT_GRID_SHAPE_OPTIONS,
    ensure_option,
    format_grid_shape,
    normalize_grid_shape,
    parse_grid_shape,
)
from rheed_capture.views.widgets.exposure_spinbox import ExposureSpinBox


class PreviewPanel(QGroupBox):
    exposure_changed = Signal(float)
    gain_changed = Signal(int)
    clahe_toggled = Signal(bool)
    grid_enabled_changed = Signal(bool)
    grid_shape_changed = Signal(int, int)

    expo_steps = 1000  # 対数スライドの解像度

    def __init__(self, expo_bounds: tuple[float, float], gain_bounds: tuple[int, int]) -> None:
        super().__init__("Preview Settings")
        self._grid_shape_options = DEFAULT_GRID_SHAPE_OPTIONS
        self._setup_ui(expo_bounds, gain_bounds)

    def _setup_ui(self, expo_bounds: tuple[float, float], gain_bounds: tuple[int, int]) -> None:
        layout = QFormLayout(self)
        self.expo_min, self.expo_max = expo_bounds
        self.gain_min, self.gain_max = gain_bounds

        self.expo_min = max(self.expo_min, 0.01)  # 小数点第2まで表示するため、最小値を調整

        # === 露光時間UI (対数スケール)
        self.spin_expo = ExposureSpinBox()
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

        # === オプション
        self.chk_processing = QCheckBox("Enable CLAHE Processing")
        self.chk_show_grid = QCheckBox("Show Grid")
        self.cmb_grid_shape = QComboBox()
        self._refresh_grid_shape_options()
        self.cmb_grid_shape.setCurrentText(format_grid_shape(*DEFAULT_GRID_SHAPE))
        self.cmb_grid_shape.setEnabled(False)

        grid_row_widget = QWidget()
        grid_row_layout = QHBoxLayout(grid_row_widget)
        grid_row_layout.setContentsMargins(0, 0, 0, 0)
        grid_row_layout.setSpacing(8)
        grid_row_layout.addWidget(self.chk_show_grid)
        grid_row_layout.addWidget(self.cmb_grid_shape)

        layout.addRow("Exposure:", self.spin_expo)
        layout.addRow("", self.slider_expo)
        layout.addRow("Gain:", self.spin_gain)
        layout.addRow("", self.slider_gain)
        layout.addRow("", self.chk_processing)
        layout.addRow("Grid:", grid_row_widget)

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
        self.chk_show_grid.toggled.connect(self._on_grid_enabled_toggled)
        self.cmb_grid_shape.currentTextChanged.connect(self._on_grid_shape_changed)

    # ==========================================
    # 対数変換ヘルパーメソッド
    # ==========================================
    def _expo_to_slider(self, expo_val: float) -> int:
        """実際の露光時間からスライダーの段階を計算"""
        # ms の範囲での最小値、最大値
        expo_ms_min, expo_ms_max = math.ceil(self.expo_min), math.floor(self.expo_max)

        if expo_val <= expo_ms_min:
            return 0
        if expo_val >= expo_ms_max:
            return self.expo_steps

        log_min, log_max = math.log10(expo_ms_min), math.log10(expo_ms_max)
        log_val = math.log10(expo_val)

        t = (log_val - log_min) / (log_max - log_min)
        return round(t * self.expo_steps)

    def _slider_to_expo(self, slider_val: int) -> float:
        """スライダーの段階から実際の露光時間(対数)を計算 (msの分解能)"""
        # ms の範囲での最小値、最大値 (0.1ms -> 1ms、99.99ms -> 99ms)
        expo_ms_min, expo_ms_max = math.ceil(self.expo_min), math.floor(self.expo_max)

        if slider_val <= 0:
            return expo_ms_min
        if slider_val >= self.expo_steps:
            return expo_ms_max

        log_min, log_max = math.log10(expo_ms_min), math.log10(expo_ms_max)
        t = slider_val / self.expo_steps

        log_val = log_min + t * (log_max - log_min)
        return round_sig_figs(10**log_val, 2)  # 有効数字2桁で変更できるように

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

    @Slot(float)
    def update_exposure_ui(self, value: float) -> None:
        """シグナルの無限ループを防ぎつつUIを更新する"""
        self.spin_expo.blockSignals(True)
        self.spin_expo.setValue(value)
        self.spin_expo.blockSignals(False)
        # スライダー同期
        self.slider_expo.blockSignals(True)
        self.slider_expo.setValue(self._expo_to_slider(value))
        self.slider_expo.blockSignals(False)

    @Slot(int)
    def update_gain_ui(self, value: int) -> None:
        self.spin_gain.blockSignals(True)
        self.spin_gain.setValue(value)
        self.spin_gain.blockSignals(False)
        # スライダー同期
        self.slider_gain.blockSignals(True)
        self.slider_gain.setValue(value)
        self.slider_gain.blockSignals(False)

    # --- CLAHE ---
    @Slot(bool)
    def update_clahe_ui(self, enabled: bool) -> None:
        self.chk_processing.blockSignals(True)
        self.chk_processing.setChecked(enabled)
        self.chk_processing.blockSignals(False)

    # --- Grid ---
    @Slot(bool)
    def _on_grid_enabled_toggled(self, enabled: bool) -> None:
        self.cmb_grid_shape.setEnabled(enabled)
        self.grid_enabled_changed.emit(enabled)

    @Slot(str)
    def _on_grid_shape_changed(self, text: str) -> None:
        rows, cols = parse_grid_shape(text)
        self.grid_shape_changed.emit(rows, cols)

    def _refresh_grid_shape_options(self) -> None:
        # 選択肢は単純な文字列一覧に変換してコンボに反映する。
        self.cmb_grid_shape.clear()
        self.cmb_grid_shape.addItems(
            [format_grid_shape(rows, cols) for rows, cols in self._grid_shape_options]
        )

    def get_grid_settings_to_save(self) -> dict:
        rows, cols = parse_grid_shape(self.cmb_grid_shape.currentText())
        return {
            "show_preview_grid": self.chk_show_grid.isChecked(),
            "preview_grid_rows": rows,
            "preview_grid_cols": cols,
        }

    def apply_grid_settings(self, enabled: bool, rows: int, cols: int) -> None:
        # 保存値が候補外でも UI で選択できるよう、候補に動的追加してから適用する。
        applied_shape = normalize_grid_shape(rows, cols, fallback=DEFAULT_GRID_SHAPE)
        self._grid_shape_options = ensure_option(self._grid_shape_options, applied_shape)
        self._refresh_grid_shape_options()
        target_label = format_grid_shape(*applied_shape)

        self.chk_show_grid.blockSignals(True)
        self.chk_show_grid.setChecked(enabled)
        self.chk_show_grid.blockSignals(False)

        self.cmb_grid_shape.blockSignals(True)
        self.cmb_grid_shape.setCurrentText(target_label)
        self.cmb_grid_shape.blockSignals(False)
        self.cmb_grid_shape.setEnabled(enabled)

    def set_controls_enabled(self, enabled: bool) -> None:
        self.spin_expo.setEnabled(enabled)
        self.slider_expo.setEnabled(enabled)
        self.spin_gain.setEnabled(enabled)
        self.slider_gain.setEnabled(enabled)
        self.chk_show_grid.setEnabled(enabled)
        self.cmb_grid_shape.setEnabled(enabled and self.chk_show_grid.isChecked())
