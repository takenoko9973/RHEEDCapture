import itertools
import logging
import time
from datetime import datetime
from typing import Never
from zoneinfo import ZoneInfo

from pypylon import pylon
from PySide6.QtCore import QObject, QThread, Signal

from rheed_capture.models.hardware.camera_device import CameraDevice
from rheed_capture.models.io.storage import ExperimentStorage

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")


class CaptureService(QThread):
    """
    自動撮影シーケンスを管理するワーカースレッド。
    UIスレッドをブロックせずに、長時間の複数露光撮影を実行する。
    """

    # 進捗シグナル (現在の枚数, 全体の枚数)
    progress_update = Signal(int, int)
    # 完了シグナル (成功したかどうか bool)
    sequence_finished = Signal(bool, str)
    # エラーメッセージシグナル
    error_occurred = Signal(str)

    def __init__(
        self,
        camera_device: CameraDevice,
        storage: ExperimentStorage,
        exposure_list: list[float],
        gain_list: list[int],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.camera = camera_device
        self.storage = storage

        exposure_list = sorted(exposure_list)  # 露光時間が短いほう優先
        gain_list = sorted(gain_list)

        # 露光時間、ゲインの全組み合わせをリストアップ
        self.conditions = list(itertools.product(exposure_list, gain_list))
        self.total_shots = len(self.conditions)

        self._is_cancelled = False
        self.max_retries = 3  # 最大試行回数

    def run(self) -> None:
        """シーケンスのメイン処理"""
        success = False
        saved_dir_name = ""

        try:
            logger.info("撮影シーケンスを開始します...")

            self.storage.start_new_sequence()  # 保存先フォルダの準備
            saved_dir_name = self.storage.get_current_sequence_dir().name  # 保存先

            #  撮影ループ
            for shot_count, (expo_ms, gain) in enumerate(self.conditions, 1):
                self._check_cancelled()

                self.progress_update.emit(shot_count, self.total_shots)

                # 1条件ごとの撮影処理 (リトライ制御付き)
                self._capture_with_retry(expo_ms, gain)

            success = True
            logger.info("撮影シーケンスが正常に完了しました。")

        except InterruptedError as e:  # 撮影キャンセル時の例外
            logger.warning(str(e))
            self.error_occurred.emit(str(e))

        except (pylon.GenericException, RuntimeError, TimeoutError) as e:
            logger.exception("シーケンス中断")
            self.error_occurred.emit(str(e))

        finally:
            self.sequence_finished.emit(success, saved_dir_name)

    def _check_cancelled(self) -> None:
        """キャンセル状態をチェックし、必要なら例外を投げる"""
        if self._is_cancelled:
            msg = "ユーザーによって撮影がキャンセルされました。"
            raise InterruptedError(msg)

    def _capture_with_retry(self, expo_ms: float, gain: int) -> None:
        """1つの条件(露光・ゲイン)での撮影とリトライロジック"""
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                # 実際の撮影処理を呼び出す
                self._execute_single_capture(expo_ms, gain)
                return  # 成功したら抜ける

            except (pylon.GenericException, RuntimeError, TimeoutError) as e:
                logger.warning("撮影エラー (Attempt %d/%d): %s", attempt, self.max_retries, e)
                last_error = e
                time.sleep(0.5)  # リトライ前に少し待機

        self._raise_max_retry_error(expo_ms, gain, last_error)

    def _raise_max_retry_error(self, expo_ms: float, gain: int, error: Exception | None) -> Never:
        """最大リトライ到達時の例外送出"""
        msg = f"最大リトライ回数に達しました。露光={expo_ms}ms, ゲイン={gain}"
        if error:
            raise RuntimeError(msg) from error

        raise RuntimeError(msg)

    def _execute_single_capture(self, expo_ms: float, gain: int) -> None:
        """純粋に1回の設定・撮影・保存のみを担当するメソッド (例外はそのまま投げる)"""
        timeout_ms = int(expo_ms + 500)

        # パラメータ設定
        self.camera.set_exposure(expo_ms)
        self.camera.set_gain(gain)

        # 撮影
        raw_data = self.camera.grab_one(timeout_ms)
        if raw_data is None:
            self._raise_grab_none_error()

        # メタデータ作成と保存
        metadata = {
            "exposure_ms": expo_ms,
            "gain": gain,
            "timestamp": datetime.now(JST).isoformat(),
            "bit_depth_sensor": 12,
            "bit_depth_saved": 16,
            "alignment": "MsbAligned",
        }
        self.storage.save_frame(raw_data, expo_ms, gain, metadata)

    def _raise_grab_none_error(self) -> Never:
        """None取得時の例外送出"""
        msg = "画像データがNoneとして返されました。"
        raise RuntimeError(msg)

    def cancel(self) -> None:
        """外部(UI)からシーケンスを安全にキャンセルするためのフラグを立てる"""
        self._is_cancelled = True
