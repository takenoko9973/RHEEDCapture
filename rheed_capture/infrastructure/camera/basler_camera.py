import logging
import time

import numpy as np
from pypylon import genicam, pylon
from pypylon.pylon import GenericException, InstantCamera, TlFactory

from rheed_capture.application.ports.camera import CameraError

logger = logging.getLogger(__name__)


class BaslerCamera:
    _camera: InstantCamera | None

    def __init__(self) -> None:
        self._camera = None

        self.converter = pylon.ImageFormatConverter()
        self.converter.OutputPixelFormat = pylon.PixelType_Mono16
        self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

    @property
    def camera(self) -> pylon.InstantCamera:
        if self._camera is None or not self._camera.IsOpen():
            msg = "カメラが接続されていません。"
            raise CameraError(msg)

        return self._camera

    def connect(self) -> None:
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

            self._apply_mandatory_settings()
            device_info = self.camera.GetDeviceInfo()
            logger.info("Connected to camera: %s", device_info.GetModelName())

        except GenericException as e:
            msg = f"カメラへの接続に失敗しました: {e}"
            raise CameraError(msg) from e

    def disconnect(self) -> None:
        if self.is_connected():
            self.stop_grabbing()
            self.camera.Close()
            self._camera = None

    def is_connected(self) -> bool:
        return self._camera is not None and self._camera.IsOpen()

    def _apply_mandatory_settings(self) -> None:
        nodemap = self.camera.GetNodeMap()

        def set_node_value(node_names: str | list[str], value: str | float | bool) -> None:
            if isinstance(node_names, str):
                node_names = [node_names]

            for node_name in node_names:
                try:
                    node = nodemap.GetNode(node_name)
                    if node is not None and genicam.IsWritable(node):
                        node.FromString(str(value))
                        return

                except genicam.LogicalErrorException:
                    continue

                except Exception as e:  # noqa: BLE001
                    logger.debug("Error accessing node '%s': %s", node_name, e)
                    continue

            logger.debug("Node '%s' is not writable or not found. Skipping.", node_name)

        set_node_value("PixelFormat", "Mono12")
        set_node_value("ExposureAuto", "Off")
        set_node_value("GainAuto", "Off")
        set_node_value("Gamma", 1.0)
        set_node_value(["BlackLevelRaw", "BlackLevel"], 0)
        set_node_value("ReverseX", True)

    def get_exposure_bounds(self) -> tuple[float, float]:
        min_us = self.camera.ExposureTimeAbs.GetMin()
        max_us = self.camera.ExposureTimeAbs.GetMax()
        return (min_us / 1000.0, max_us / 1000.0)

    def get_gain_bounds(self) -> tuple[int, int]:
        min_gain = self.camera.GainRaw.GetMin()
        max_gain = self.camera.GainRaw.GetMax()
        return (min_gain, max_gain)

    def set_exposure(self, exposure_ms: float) -> None:
        exposure_us = exposure_ms * 1000.0
        self.camera.ExposureTimeAbs.SetValue(exposure_us)

    def get_exposure(self) -> float:
        exposure_us = self.camera.ExposureTimeAbs.GetValue()
        return exposure_us / 1000.0

    def set_gain(self, gain: int) -> None:
        self.camera.GainRaw.SetValue(gain)

    def get_gain(self) -> float:
        return self.camera.GainRaw.GetValue()

    def start_preview_grab(self) -> None:
        if self.is_connected() and not self.camera.IsGrabbing():
            self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
            time.sleep(0.1)

    def stop_grabbing(self) -> None:
        if self.is_connected() and self.camera.IsGrabbing():
            self.camera.StopGrabbing()

    def grab_one(self, timeout_ms: int) -> np.ndarray | None:
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

    def retrieve_preview_frame(self, timeout_ms: int = 1000) -> np.ndarray | None:
        if not self.is_connected() or not self.camera.IsGrabbing():
            return None

        try:
            with self.camera.RetrieveResult(timeout_ms, pylon.TimeoutHandling_Return) as result:
                if result.GrabSucceeded():
                    image = self.converter.Convert(result)
                    return image.GetArray()

                return None

        except pylon.GenericException as e:
            logger.exception("プレビュー画像の取得中にエラーが発生しました")
            msg = f"プレビュー画像の取得に失敗しました: {e}"
            raise CameraError(msg) from e


CameraDevice = BaslerCamera
