import math
from collections.abc import Callable
from typing import Any, cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget


def display_interval_ms(refresh_rate_hz: float) -> int:
    """表示refresh rateを超えないQTimer間隔へ変換する。"""
    if refresh_rate_hz <= 0:
        msg = "Display refresh rate must be greater than zero."
        raise ValueError(msg)
    return max(1, math.ceil(1000.0 / refresh_rate_hz))


class DisplayRefreshController:
    """MainWindowのactive screenに表示更新Timerを追従させる。"""

    def __init__(
        self,
        window: QWidget,
        refresh_display: Callable[[], None],
        set_refresh_rate: Callable[[float], None],
    ) -> None:
        """表示先WidgetとPreview更新callbackを保持する。"""
        self._window = window
        self._set_refresh_rate = set_refresh_rate
        self.timer = QTimer(window)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(refresh_display)
        self.active_hz = 0.0
        self._screen: object | None = None
        self._refresh_signal: object | None = None
        self._window_handle: object | None = None
        self._is_stopped = False

    def bind_window_screen(self) -> None:
        """native windowのscreenChangedへ接続し、現在screenを同期する。"""
        if self._is_stopped:
            return

        window_handle = self._window.windowHandle()
        if window_handle is not None and window_handle is not self._window_handle:
            window_handle.screenChanged.connect(self.on_screen_changed)
            self._window_handle = window_handle

        active_screen = self._window.screen()
        if active_screen is not self._screen:
            self.on_screen_changed(active_screen)
        elif active_screen is not None:
            self.on_refresh_rate_changed()

    def on_screen_changed(self, screen: object | None) -> None:
        """screen移動時にrefresh rate signalと表示Timerを切り替える。"""
        if self._is_stopped:
            return

        if self._refresh_signal is not None:
            cast("Any", self._refresh_signal).disconnect(self.on_refresh_rate_changed)
            self._refresh_signal = None

        self._screen = screen
        if screen is None:
            self._stop()
            return

        refresh_signal = getattr(screen, "refreshRateChanged", None)
        if refresh_signal is not None:
            refresh_signal.connect(self.on_refresh_rate_changed)
            self._refresh_signal = refresh_signal
        self.on_refresh_rate_changed()

    def on_refresh_rate_changed(self, refresh_rate_hz: float | None = None) -> None:
        """refresh rate変更をTimer間隔とPreview診断値へ反映する。"""
        if self._is_stopped:
            return

        if refresh_rate_hz is None:
            if self._screen is None:
                return
            refresh_rate_hz = float(cast("Any", self._screen).refreshRate())

        if refresh_rate_hz <= 0:
            self._stop()
            return

        self.active_hz = float(refresh_rate_hz)
        self.timer.setInterval(display_interval_ms(self.active_hz))
        self._set_refresh_rate(self.active_hz)
        if not self.timer.isActive():
            self.timer.start()

    def stop(self) -> None:
        """表示更新Timerを停止する。"""
        self._is_stopped = True
        self.timer.stop()

    def _stop(self) -> None:
        """無効な表示先に対してTimerと診断値を停止状態へ戻す。"""
        self.timer.stop()
        self.active_hz = 0.0
        self._set_refresh_rate(0.0)
