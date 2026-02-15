import numpy as np
from PySide6.QtCore import QRectF, Qt, Slot, QPointF
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF, QPaintEvent
from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QWidget


class HistogramWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(150)
        self.setStyleSheet("background-color: #1e1e1e; border-radius: 4px;")

        self.hist_data: np.ndarray | None = None

    def set_data(self, hist_data: np.ndarray) -> None:
        self.hist_data = hist_data
        self.update()  # paintEventをトリガーして再描画

    def paintEvent(self, event: QPaintEvent) -> None:
        """QPainterを使った高速なカスタム描画"""
        super().paintEvent(event)
        if self.hist_data is None or len(self.hist_data) == 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()

        # 線の色と内側の塗りつぶし色を設定して描画
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(100, 200, 255, 180)))

        # Y軸（ピクセル数）を対数スケールに変換 (log(1 + x))
        log_hist = np.log1p(self.hist_data)
        max_val = np.max(log_hist)
        if max_val == 0:
            max_val = 1.0

        bin_width = width / len(self.hist_data)

        # 棒グラフ状に描画
        for i, val in enumerate(self.hist_data):
            h = (val / max_val) * height
            rect = QRectF(i * bin_width, height - h, bin_width, h)
            painter.drawRect(rect)

class HistogramPanel(QGroupBox):
    def __init__(self) -> None:
        super().__init__("Intensity 12bit Histogram (Log Scale)")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.hist_widget = HistogramWidget()
        layout.addWidget(self.hist_widget)

        # 統計量表示用ラベル (数値がブレても枠がガタつかないよう等幅フォントを指定)
        self.lbl_stats = QLabel("Mean ---    Std. Dev. ---")
        self.lbl_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_stats.setStyleSheet("font-family: monospace; font-size: 13px;")
        layout.addWidget(self.lbl_stats)

    @Slot(np.ndarray, float, float)
    def update_histogram(self, hist_data: np.ndarray, mean_val: float, std_val: float) -> None:
        self.hist_widget.set_data(hist_data)
        self.lbl_stats.setText(f"Mean {mean_val:4.2f}    Std. Dev. {std_val:4.2f}")
