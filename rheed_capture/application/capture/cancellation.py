from __future__ import annotations


class CaptureCancelled(InterruptedError):  # noqa: N818
    """撮影処理がユーザー操作で中断されたことを表す共通例外。"""


class CancellationToken:
    """撮影方式に依存しないキャンセル状態の共有オブジェクト。"""

    def __init__(self) -> None:
        self._is_cancelled = False

    def cancel(self) -> None:
        """外側のWorkerやViewModelからキャンセル要求を記録する。"""
        self._is_cancelled = True

    def is_cancelled(self) -> bool:
        """キャンセル要求済みならTrueを返す。"""
        return self._is_cancelled

    def raise_if_cancelled(self) -> None:
        """キャンセル要求済みなら撮影ループを抜けるための例外を投げる。"""
        if self._is_cancelled:
            msg = "ユーザーによって撮影がキャンセルされました。"
            raise CaptureCancelled(msg)
