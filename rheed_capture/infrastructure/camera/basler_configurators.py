from __future__ import annotations

import logging
from typing import Protocol

from pypylon import genicam, pylon

from rheed_capture.application.ports.camera import CameraError

logger = logging.getLogger(__name__)

CAMERA_EMULATION_ENV_VAR = "PYLON_CAMEMU"
CAMERA_EMULATION_ROI = (720, 540)
CAMERA_EMULATION_DEVICE_CLASS = "BaslerCamEmu"
CAMERA_EMULATION_PIXEL_FORMAT = "Mono12"
CAMERA_PIXEL_FORMAT = "Mono12Packed"
NodeValue = str | int | float | bool


class _WritableNode(Protocol):
    """FromStringで値を書き込めるGenICam node。"""

    def FromString(self, value: str, verify: bool = True) -> None:  # noqa: N802
        """文字列化された値をnodeへ書き込む。"""

    def ToString(self) -> str:  # noqa: N802
        """現在値を文字列表現で返す。"""


class _NodeMap(Protocol):
    """node名からGenICam nodeを取得できるnodemap。"""

    def GetNode(self, name: str) -> _WritableNode | None:  # noqa: N802
        """指定名のnodeを返す。"""


def _set_node_value(
    nodemap: _NodeMap,
    node_names: str | list[str],
    value: NodeValue,
) -> bool:
    """利用可能な最初のnodeへ値を書き込む。"""
    if isinstance(node_names, str):
        node_names = [node_names]

    for node_name in node_names:
        try:
            node = nodemap.GetNode(node_name)
            if node is not None and genicam.IsWritable(node):
                node.FromString(str(value))
                return True

        except genicam.LogicalErrorException:
            continue

        except Exception as e:  # noqa: BLE001
            logger.debug("Error accessing node '%s': %s", node_name, e)
            continue

    logger.debug("Node '%s' is not writable or not found. Skipping.", node_name)
    return False


class BaslerCameraConfigurator(Protocol):
    """接続済みBasler cameraへ初期設定を適用するport。"""

    def apply(self, camera: pylon.InstantCamera) -> None:
        """接続済みcameraへ設定を適用する。"""


class BaslerMandatorySettings:
    """実機とエミュレータで共通の必須設定を適用する。"""

    def apply(self, camera: pylon.InstantCamera) -> None:
        """撮影に必要な共通カメラ設定を適用する。"""
        nodemap = camera.GetNodeMap()

        device_class = camera.GetDeviceInfo().GetDeviceClass()
        pixel_format = (
            CAMERA_EMULATION_PIXEL_FORMAT
            if device_class == CAMERA_EMULATION_DEVICE_CLASS
            else CAMERA_PIXEL_FORMAT
        )
        _set_required_pixel_format(nodemap, pixel_format)
        _set_node_value(nodemap, "ExposureAuto", "Off")
        _set_node_value(nodemap, "GainAuto", "Off")
        _set_node_value(nodemap, "Gamma", 1.0)
        _set_node_value(nodemap, ["BlackLevelRaw", "BlackLevel"], 0)
        _set_node_value(nodemap, "ReverseX", True)


def _set_required_pixel_format(nodemap: _NodeMap, expected: str) -> None:
    """PixelFormat nodeを必須値へ設定し、書込み結果を検証する。"""
    node_name = "PixelFormat"
    try:
        node = nodemap.GetNode(node_name)
    except genicam.GenericException as e:
        msg = f"必須GenICam node '{node_name}' (期待値 '{expected}') の取得に失敗しました: {e}"
        raise CameraError(msg) from e

    if node is None:
        msg = f"必須GenICam node '{node_name}' (期待値 '{expected}') が存在しません。"
        raise CameraError(msg)

    try:
        if not genicam.IsAvailable(node):
            msg = f"必須GenICam node '{node_name}' (期待値 '{expected}') が利用できません。"
            raise CameraError(msg)
        if not genicam.IsWritable(node):
            msg = f"必須GenICam node '{node_name}' (期待値 '{expected}') は書き込みできません。"
            raise CameraError(msg)
    except genicam.GenericException as e:
        msg = f"必須GenICam node '{node_name}' (期待値 '{expected}') の状態確認に失敗しました: {e}"
        raise CameraError(msg) from e

    try:
        node.FromString(expected)
    except genicam.GenericException as e:
        msg = f"必須GenICam node '{node_name}' (期待値 '{expected}') を設定できません: {e}"
        raise CameraError(msg) from e

    try:
        if not genicam.IsReadable(node):
            msg = f"必須GenICam node '{node_name}' (期待値 '{expected}') は読み取りできません。"
            raise CameraError(msg)
        actual = str(node.ToString())
    except genicam.GenericException as e:
        msg = f"必須GenICam node '{node_name}' (期待値 '{expected}') の読戻しに失敗しました: {e}"
        raise CameraError(msg) from e

    if actual != expected:
        msg = (
            f"必須GenICam node '{node_name}' の読戻し値 '{actual}' が "
            f"期待値 '{expected}' と一致しません。"
        )
        raise CameraError(msg)


class BaslerCameraEmulationSettings:
    """pylon Camera Emulation専用の設定を適用する。"""

    def __init__(self, width: int = 720, height: int = 540) -> None:
        """エミュレータ出力用のROIサイズを保持する。"""
        self.width = width
        self.height = height

    def apply(self, camera: pylon.InstantCamera) -> None:
        """エミュレータのImage ROIを左上基準で設定する。"""
        applied_width, applied_height = self._set_image_roi(camera, self.width, self.height)
        logger.info(
            "Applied camera emulation ROI: %sx%s",
            applied_width,
            applied_height,
        )

    def _set_image_roi(
        self,
        camera: pylon.InstantCamera,
        width: int,
        height: int,
    ) -> tuple[int, int]:
        """Image ROIを設定し、実際に適用した幅と高さを返す。"""
        was_grabbing = camera.IsGrabbing()
        if was_grabbing:
            camera.StopGrabbing()

        nodemap = camera.GetNodeMap()

        # Offsetを先に戻し、Width/Heightが最大制約に引っかからない状態にする。
        _set_node_value(nodemap, "OffsetX", 0)
        _set_node_value(nodemap, "OffsetY", 0)

        applied_width = self._clamp_to_integer_node(width, camera.Width)
        applied_height = self._clamp_to_integer_node(height, camera.Height)
        _set_node_value(nodemap, "Width", applied_width)
        _set_node_value(nodemap, "Height", applied_height)

        if was_grabbing:
            camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

        return (applied_width, applied_height)

    def _clamp_to_integer_node(self, value: int, node: genicam.IInteger) -> int:
        """Integer nodeのMin/Max/Inc制約に合わせて値を丸める。"""
        min_value = int(node.GetMin())
        max_value = int(node.GetMax())
        increment = int(node.GetInc())

        clamped_value = max(min_value, min(max_value, value))
        if increment <= 0:
            return clamped_value

        return min_value + ((clamped_value - min_value) // increment) * increment
