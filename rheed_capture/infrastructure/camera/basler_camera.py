import logging
import threading
import time
from collections.abc import Sequence

import numpy as np
from pypylon import pylon
from pypylon.pylon import GenericException, InstantCamera, TlFactory

from rheed_capture.application.ports.camera import CameraError
from rheed_capture.infrastructure.camera.basler_configurators import (
    BaslerCameraConfigurator,
    BaslerMandatorySettings,
)

logger = logging.getLogger(__name__)


class BaslerCamera:
    _camera: InstantCamera | None

    def __init__(self, configurators: Sequence[BaslerCameraConfigurator] | None = None) -> None:
        """カメラデバイスラッパーを初期化する。"""
        self._camera = None
        self._lock = threading.RLock()
        self._configurators = tuple(configurators or (BaslerMandatorySettings(),))

        self.converter = pylon.ImageFormatConverter()
        self.converter.OutputPixelFormat = pylon.PixelType_Mono16
        self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

    @property
    def camera(self) -> pylon.InstantCamera:
        """接続済みのpypylonカメラインスタンスを返す。"""
        if self._camera is None or not self._camera.IsOpen():
            msg = "カメラが接続されていません。"
            raise CameraError(msg)

        return self._camera

    def connect(self) -> None:
        """最初に見つかったBaslerカメラへ接続して初期設定を適用する。"""
        if self.is_connected():
            return

        try:
            tl_factory = TlFactory.GetInstance()
            devices = tl_factory.EnumerateDevices()
            if not devices:
                msg = "カメラが見つかりません。"
                raise CameraError(msg)

            self._camera = InstantCamera(tl_factory.CreateFirstDevice())
            self._camera.Open()

            for configurator in self._configurators:
                configurator.apply(self.camera)

            device_info = self.camera.GetDeviceInfo()
            logger.info("Connected to camera: %s", device_info.GetModelName())

        except GenericException as e:
            msg = f"カメラへの接続に失敗しました: {e}"
            raise CameraError(msg) from e

    def disconnect(self) -> None:
        """接続中のカメラを停止して切断する。"""
        with self._lock:
            if self.is_connected():
                self.stop_grabbing()
                self.camera.Close()
                self._camera = None

    def is_connected(self) -> bool:
        """カメラがオープン済みかどうかを返す。"""
        return self._camera is not None and self._camera.IsOpen()

    def get_exposure_bounds(self) -> tuple[float, float]:
        """露光時間の設定可能範囲をミリ秒単位で返す。"""
        min_us = self.camera.ExposureTimeAbs.GetMin()
        max_us = self.camera.ExposureTimeAbs.GetMax()
        return (min_us / 1000.0, max_us / 1000.0)

    def get_gain_bounds(self) -> tuple[int, int]:
        """ゲインの設定可能範囲を返す。"""
        min_gain = self.camera.GainRaw.GetMin()
        max_gain = self.camera.GainRaw.GetMax()
        return (min_gain, max_gain)

    def set_exposure(self, exposure_ms: float) -> None:
        """露光時間をミリ秒単位で設定する。"""
        with self._lock:
            exposure_us = exposure_ms * 1000.0
            self.camera.ExposureTimeAbs.SetValue(exposure_us)

    def get_exposure(self) -> float:
        """現在の露光時間をミリ秒単位で返す。"""
        with self._lock:
            exposure_us = self.camera.ExposureTimeAbs.GetValue()
            return exposure_us / 1000.0

    def set_gain(self, gain: int) -> None:
        """ゲインを設定する。"""
        with self._lock:
            self.camera.GainRaw.SetValue(gain)

    def get_gain(self) -> float:
        """現在のゲインを返す。"""
        with self._lock:
            return self.camera.GainRaw.GetValue()

    def start_preview_grab(self) -> None:
        """プレビュー用の連続取得を開始する。"""
        with self._lock:
            if self.is_connected() and not self.camera.IsGrabbing():
                self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
                time.sleep(0.1)

    def stop_grabbing(self) -> None:
        """実行中の画像取得を停止する。"""
        with self._lock:
            if self.is_connected() and self.camera.IsGrabbing():
                self.camera.StopGrabbing()

    def grab_one(self, timeout_ms: int) -> np.ndarray | None:
        """指定タイムアウトで1フレーム取得する。"""
        with self._lock:
            if not self.is_connected():
                msg = "カメラが接続されていません。"
                raise CameraError(msg)

            if self.camera.IsGrabbing():
                msg = "現在プレビュー実行中です。StopGrabbingを呼び出してください。"
                raise RuntimeError(msg)

            try:
                with self.camera.GrabOne(timeout_ms) as result:
                    if result.GrabSucceeded():
                        image = self.converter.Convert(result)
                        return image.GetArray()

                    return None

            except pylon.GenericException as e:
                logger.exception("画像の取得中にエラーが発生しました")
                msg = f"カメラ画像の取得に失敗しました: {e}"
                raise CameraError(msg) from e

    def _is_valid_grab_result(self, result: object) -> bool:
        """RetrieveResultの戻り値が有効な結果かどうかを返す。"""
        is_valid = getattr(result, "IsValid", None)
        if callable(is_valid):
            return bool(is_valid())
        return result is not None

    def retrieve_preview_frame(self, timeout_ms: int = 1000) -> np.ndarray | None:
        """プレビュー連続取得中の次フレームを返す。"""
        with self._lock:
            if not self.is_connected() or not self.camera.IsGrabbing():
                return None

            try:
                with self.camera.RetrieveResult(
                    timeout_ms,
                    pylon.TimeoutHandling_Return,
                ) as result:
                    if not self._is_valid_grab_result(result):
                        return None

                    if result.GrabSucceeded():
                        image = self.converter.Convert(result)
                        return image.GetArray()

                    return None

            except pylon.GenericException as e:
                logger.exception("プレビュー画像の取得中にエラーが発生しました")
                msg = f"プレビュー画像の取得に失敗しました: {e}"
                raise CameraError(msg) from e


CameraDevice = BaslerCamera
