from __future__ import annotations

import logging
from typing import Protocol

from pypylon import genicam, pylon

logger = logging.getLogger(__name__)

CAMERA_EMULATION_ENV_VAR = "PYLON_CAMEMU"
CAMERA_EMULATION_ROI = (720, 540)
NodeValue = str | int | float | bool


class _WritableNode(Protocol):
    """FromStringで値を書き込めるGenICam node。"""

    def FromString(self, value: str, verify: bool = True) -> None:  # noqa: N802
        """文字列化された値をnodeへ書き込む。"""


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

        _set_node_value(nodemap, "PixelFormat", "Mono12")
        _set_node_value(nodemap, "ExposureAuto", "Off")
        _set_node_value(nodemap, "GainAuto", "Off")
        _set_node_value(nodemap, "Gamma", 1.0)
        _set_node_value(nodemap, ["BlackLevelRaw", "BlackLevel"], 0)
        _set_node_value(nodemap, "ReverseX", True)


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
