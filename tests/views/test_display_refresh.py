from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from rheed_capture.presentation.qt.display_refresh import (
    DisplayRefreshController,
    display_interval_ms,
)


class _FakeScreen(QObject):
    """refresh rate変更を発行できるQScreen相当のdouble。"""

    refreshRateChanged = Signal(float)  # noqa: N815

    def __init__(self, rate_hz: float) -> None:
        """初期refresh rateを保持する。"""
        super().__init__()
        self.rate_hz = rate_hz

    def refreshRate(self) -> float:  # noqa: N802
        """現在のrefresh rateを返す。"""
        return self.rate_hz


@pytest.mark.parametrize(
    ("refresh_rate_hz", "expected_interval_ms"),
    [(60.0, 17), (120.0, 9), (144.0, 7)],
)
def test_display_interval_rounds_up_to_not_exceed_refresh_rate(
    refresh_rate_hz: float,
    expected_interval_ms: int,
) -> None:
    """Timer間隔は表示refresh rateを超えないようミリ秒単位で切り上げる。"""
    assert display_interval_ms(refresh_rate_hz) == expected_interval_ms


def test_screen_change_disconnects_previous_refresh_signal(qtbot: QtBot) -> None:
    """screen移動後は旧screenのrefresh rate変更を反映しない。"""
    window = QWidget()
    qtbot.addWidget(window)
    set_refresh_rate = MagicMock()
    controller = DisplayRefreshController(window, MagicMock(), set_refresh_rate)
    first_screen = _FakeScreen(60.0)
    second_screen = _FakeScreen(144.0)

    controller.on_screen_changed(first_screen)
    controller.on_screen_changed(second_screen)
    set_refresh_rate.reset_mock()

    first_screen.refreshRateChanged.emit(30.0)

    assert controller.active_hz == 144.0
    assert controller.timer.interval() == 7
    set_refresh_rate.assert_not_called()
    controller.stop()


@pytest.mark.parametrize("invalid_refresh_rate_hz", [0.0, -1.0])
def test_invalid_refresh_rate_stops_timer_and_clears_diagnostic_rate(
    qtbot: QtBot,
    invalid_refresh_rate_hz: float,
) -> None:
    """無効なrefresh rateではTimerを停止し診断値を0へ戻す。"""
    window = QWidget()
    qtbot.addWidget(window)
    set_refresh_rate = MagicMock()
    controller = DisplayRefreshController(window, MagicMock(), set_refresh_rate)
    controller.on_screen_changed(_FakeScreen(60.0))
    set_refresh_rate.reset_mock()

    controller.on_refresh_rate_changed(invalid_refresh_rate_hz)

    assert controller.timer.isActive() is False
    assert controller.active_hz == 0.0
    set_refresh_rate.assert_called_once_with(0.0)


def test_stop_explicitly_stops_active_timer(qtbot: QtBot) -> None:
    """明示停止でactiveな表示更新Timerを停止する。"""
    window = QWidget()
    qtbot.addWidget(window)
    controller = DisplayRefreshController(window, MagicMock(), MagicMock())
    controller.on_screen_changed(_FakeScreen(60.0))

    controller.stop()

    assert controller.timer.isActive() is False


def test_stop_prevents_screen_signal_from_restarting_refresh(qtbot: QtBot) -> None:
    """停止後のscreen通知ではTimerと診断refresh rateを再開しない。"""
    screen = _FakeScreen(60.0)
    window = QWidget()
    qtbot.addWidget(window)
    refresh_display = MagicMock()
    set_refresh_rate = MagicMock()
    controller = DisplayRefreshController(window, refresh_display, set_refresh_rate)
    controller.on_screen_changed(screen)
    controller.stop()
    set_refresh_rate.reset_mock()

    screen.refreshRateChanged.emit(144.0)

    assert controller.timer.isActive() is False
    set_refresh_rate.assert_not_called()
    refresh_display.assert_not_called()


def test_rebinding_same_screen_is_idempotent(qtbot: QtBot) -> None:
    """同じscreenへ再bindしてもrefresh rate signalを重複接続しない。"""
    screen = _FakeScreen(60.0)
    window = QWidget()
    qtbot.addWidget(window)
    set_refresh_rate = MagicMock()
    controller = DisplayRefreshController(window, MagicMock(), set_refresh_rate)

    controller.on_screen_changed(screen)
    controller.on_screen_changed(screen)
    set_refresh_rate.reset_mock()

    screen.refreshRateChanged.emit(144.0)

    assert controller.active_hz == 144.0
    assert controller.timer.interval() == 7
    set_refresh_rate.assert_called_once_with(144.0)
    controller.stop()
