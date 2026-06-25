from __future__ import annotations

import threading


class CaptureCancelled(InterruptedError):  # noqa: N818
    """撮影処理がユーザー操作で中断されたことを表す共通例外。"""


class CancellationToken:
    """撮影方式に依存しないキャンセル状態の共有オブジェクト。"""

    def __init__(self) -> None:
        """スレッド間で共有するキャンセルイベントを初期化する。"""
        self._event = threading.Event()

    def cancel(self) -> None:
        """外側のWorkerやViewModelからキャンセル要求を記録する。"""
        self._event.set()

    def is_cancelled(self) -> bool:
        """キャンセル要求済みならTrueを返す。"""
        return self._event.is_set()

    def wait(self, timeout_sec: float) -> bool:
        """キャンセルされるか、指定秒数が経過するまで待つ。"""
        return self._event.wait(timeout_sec)

    def raise_if_cancelled(self) -> None:
        """キャンセル要求済みなら撮影ループを抜けるための例外を投げる。"""
        if self.is_cancelled():
            msg = "ユーザーによって撮影がキャンセルされました。"
            raise CaptureCancelled(msg)
