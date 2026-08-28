from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import numpy as np
import pytest
import tifffile
from pypylon import pylon

from rheed_capture.application.capture.angle_scan import (
    AngleScanSettings,
    build_angle_scan_document_from_conditions,
)
from rheed_capture.application.capture.frame_capturer import CapturedFrame, CaptureTiming
from rheed_capture.application.ports.camera import (
    CameraError,
    FrameReadback,
    ImageFormatSnapshot,
)
from rheed_capture.domain.capture_condition import CaptureCondition
from rheed_capture.infrastructure.camera.basler_camera import BaslerCamera, CameraState
from rheed_capture.infrastructure.config.schema import AcquisitionSettings, AppSettingsData
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage
from rheed_capture.presentation.qt.panels.acquisition_settings import AcquisitionSettingsPanel
from rheed_capture.presentation.qt.preview.processor import PreviewInput, PreviewPipeline
from rheed_capture.presentation.qt.widgets.histogram_viewer import HistogramPanel

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot


def _readback() -> FrameReadback:
    """テスト用のcamera読戻し値を作る。"""
    return FrameReadback(
        exposure_ms=10.0,
        gain=0,
        camera_timestamp_ticks=1,
        camera_timestamp_frequency_hz=125_000_000,
        source="camera",
    )


def _captured_frame(image: np.ndarray, image_format: ImageFormatSnapshot) -> CapturedFrame:
    """指定形式のCapturedFrameを作る。"""
    return CapturedFrame(
        image=image,
        condition=CaptureCondition(exposure_ms=10.0, gain=0),
        readback=_readback(),
        timing=CaptureTiming(
            trigger_issued_at=datetime.fromisoformat("2026-08-28T12:00:00+09:00"),
            trigger_issued_monotonic_sec=1.0,
        ),
        image_format=image_format,
    )


def _read_tiff(path: Path) -> tuple[np.ndarray, dict[str, object]]:
    """TIFFの配列とImageDescriptionを読み戻す。"""
    with tifffile.TiffFile(path) as tif:
        image = tif.asarray()
        page = cast("tifffile.TiffPage", tif.pages[0])
        metadata = json.loads(page.tags["ImageDescription"].value)
    return image, metadata


def test_sensor_bit_depth_settings_are_strict_and_round_trip() -> None:
    """センサbit depthは8/12の整数だけを受け付け、欠落時は12を使う。"""
    default_settings = AppSettingsData.from_dict({})
    assert default_settings.acquisition.sensor_bit_depth == 12
    assert (
        AppSettingsData.from_dict({"acquisition": {}})
        .to_dict()["acquisition"]["sensor_bit_depth"]
        == 12
    )

    settings = AppSettingsData.from_dict({"acquisition": {"sensor_bit_depth": 8}})
    assert settings.acquisition.sensor_bit_depth == 8
    saved = settings.to_dict()
    assert saved["acquisition"]["sensor_bit_depth"] == 8
    assert AppSettingsData.from_dict(saved).acquisition.sensor_bit_depth == 8


@pytest.mark.parametrize("value", [True, False, 7, 16, 8.0, "8", None, {}, []])
def test_sensor_bit_depth_rejects_invalid_present_values(value: object) -> None:
    """存在するsensor_bit_depthの不正値を既定値へ置換しない。"""
    with pytest.raises(ValueError, match="sensor_bit_depth"):
        AppSettingsData.from_dict({"acquisition": {"sensor_bit_depth": value}})


def test_acquisition_panel_selects_sensor_bit_depth_and_locks_it(qtbot: QtBot) -> None:
    """Acquisition Settingsのbit depth selectorが保存値と撮影中lockへ接続される。"""
    panel = AcquisitionSettingsPanel()
    qtbot.addWidget(panel)

    assert panel.cmb_sensor_bit_depth.count() == 2
    assert {panel.cmb_sensor_bit_depth.itemData(index) for index in range(2)} == {8, 12}
    assert "ビット" in panel.cmb_sensor_bit_depth.toolTip()

    panel.cmb_sensor_bit_depth.setCurrentIndex(
        panel.cmb_sensor_bit_depth.findData(8)
    )
    assert panel.get_settings_to_save().sensor_bit_depth == 8

    panel.apply_settings(AcquisitionSettings(sensor_bit_depth=12))
    assert panel.get_settings_to_save().sensor_bit_depth == 12
    panel.set_controls_enabled(False)
    assert panel.cmb_sensor_bit_depth.isEnabled() is False


class _PixelFormatNode:
    """Basler PixelFormat設定用の最小node double。"""

    def __init__(self, value: str = "Mono12", *, update_value: bool = True) -> None:
        """初期値を保持する。"""
        self.value = value
        self.update_value = update_value
        self.write_count = 0

    def FromString(self, value: str, verify: bool = True) -> None:  # noqa: ARG002, N802
        """書込み値を保持する。"""
        self.write_count += 1
        if self.update_value:
            self.value = value

    def ToString(self) -> str:  # noqa: N802
        """現在値を返す。"""
        return self.value


@pytest.mark.parametrize(
    ("device_class", "sensor_bit_depth", "expected_pixel_format", "output_pixel_type", "alignment"),
    [
        ("BaslerCamEmu", 12, "Mono12", pylon.PixelType_Mono16, "MsbAligned"),
        ("BaslerGigE", 12, "Mono12Packed", pylon.PixelType_Mono16, "MsbAligned"),
        ("BaslerCamEmu", 8, "Mono8", pylon.PixelType_Mono8, None),
        ("BaslerGigE", 8, "Mono8", pylon.PixelType_Mono8, None),
    ],
)
def test_camera_configures_exact_format_and_returns_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    device_class: str,
    sensor_bit_depth: int,
    expected_pixel_format: str,
    output_pixel_type: int,
    alignment: str | None,
) -> None:
    """DeviceClassとbit depthに対応する形式、converter、snapshotを確定する。"""
    node = _PixelFormatNode()
    camera = MagicMock()
    camera.IsOpen.return_value = True
    camera.GetDeviceInfo.return_value.GetDeviceClass.return_value = device_class
    camera.GetNodeMap.return_value.GetNode.return_value = node

    monkeypatch.setattr(
        "rheed_capture.infrastructure.camera.basler_camera.genicam.IsAvailable",
        lambda _: True,
    )
    monkeypatch.setattr(
        "rheed_capture.infrastructure.camera.basler_camera.genicam.IsWritable",
        lambda _: True,
    )
    monkeypatch.setattr(
        "rheed_capture.infrastructure.camera.basler_camera.genicam.IsReadable",
        lambda _: True,
    )

    device = BaslerCamera()
    device._camera = camera  # noqa: SLF001
    device._state = CameraState.IDLE  # noqa: SLF001

    snapshot = device.configure_image_format(sensor_bit_depth)

    assert node.value == expected_pixel_format
    assert node.write_count == 1
    assert device.converter.OutputPixelFormat == output_pixel_type
    if alignment is not None:
        assert device.converter.OutputBitAlignment.GetValue() == alignment
    assert snapshot == ImageFormatSnapshot(
        bit_depth_sensor=sensor_bit_depth,
        bit_depth_saved=8 if sensor_bit_depth == 8 else 16,
        pixel_format=expected_pixel_format,
        alignment=None if sensor_bit_depth == 8 else "MsbAligned",
    )


def test_camera_format_readback_mismatch_fails_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """要求したPixelFormatの読戻し不一致をCameraErrorとして返す。"""
    node = _PixelFormatNode(update_value=False)
    camera = MagicMock()
    camera.IsOpen.return_value = True
    camera.GetDeviceInfo.return_value.GetDeviceClass.return_value = "BaslerGigE"
    camera.GetNodeMap.return_value.GetNode.return_value = node

    monkeypatch.setattr(
        "rheed_capture.infrastructure.camera.basler_camera.genicam.IsAvailable",
        lambda _: True,
    )
    monkeypatch.setattr(
        "rheed_capture.infrastructure.camera.basler_camera.genicam.IsWritable",
        lambda _: True,
    )
    monkeypatch.setattr(
        "rheed_capture.infrastructure.camera.basler_camera.genicam.IsReadable",
        lambda _: True,
    )

    device = BaslerCamera()
    device._camera = camera  # noqa: SLF001
    device._state = CameraState.IDLE  # noqa: SLF001

    with pytest.raises(CameraError, match="Mono12Packed"):
        device.configure_image_format(12)


def test_preview_pipeline_preserves_8bit_scale_and_12bit_sensor_scale(qtbot: QtBot) -> None:
    """Preview/Graphがsnapshotに応じて8-bitと12-bitの強度scaleを使う。"""
    pipeline = PreviewPipeline()
    images: list[np.ndarray] = []
    histograms: list[tuple[np.ndarray, float, float]] = []
    pipeline.image_ready.connect(images.append)
    pipeline.histogram_ready.connect(
        lambda histogram, mean, std: histograms.append((histogram, mean, std))
    )
    pipeline.start()

    frame = PreviewInput(
        np.array([[0, 127], [255, 10]], dtype=np.uint8),
        ImageFormatSnapshot(8, 8, "Mono8", None),
    )
    try:
        assert pipeline.submit_frame(frame)
        qtbot.waitUntil(pipeline.poll_results, timeout=1000)
        assert np.array_equal(images[-1], frame.image)
        assert histograms[-1][1] == pytest.approx(98.0)
        assert histograms[-1][0][255] == 1

        raw_12 = np.array([[0, 4095 << 4]], dtype=np.uint16)
        assert pipeline.submit_frame(
            PreviewInput(raw_12, ImageFormatSnapshot(12, 16, "Mono12", "MsbAligned"))
        )
        qtbot.waitUntil(lambda: pipeline.poll_results() and len(histograms) == 2, timeout=1000)
        assert histograms[-1][1] == pytest.approx(2047.5)
        assert histograms[-1][0][-1] == 1
    finally:
        pipeline.stop()


def test_histogram_label_reflects_selected_sensor_scale(qtbot: QtBot) -> None:
    """Histogramのlabelが8-bitと12-bitの実強度範囲を示す。"""
    panel = HistogramPanel()
    qtbot.addWidget(panel)

    panel.set_sensor_bit_depth(8)
    assert "0..255" in panel.title()
    panel.set_sensor_bit_depth(12)
    assert "0..4095" in panel.title()


@pytest.mark.parametrize(
    ("image_format", "image"),
    [
        (
            ImageFormatSnapshot(8, 8, "Mono8", None),
            np.array([[1, 255]], dtype=np.uint8),
        ),
        (
            ImageFormatSnapshot(12, 16, "Mono12", "MsbAligned"),
            np.array([[1 << 4, 4095 << 4]], dtype=np.uint16),
        ),
    ],
)
def test_sequence_tiff_and_scan_document_store_image_format(
    tmp_path: Path,
    image_format: ImageFormatSnapshot,
    image: np.ndarray,
) -> None:
    """全modeの通常・蓄積TIFFとscan.jsonがsnapshotとdtypeを保存する。"""
    storage = ExperimentStorage(tmp_path)
    session = storage.start_sequence_session(image_format=image_format)
    frame = _captured_frame(image, image_format)
    tiff_path = session.save_frame(frame)
    accumulation_path = session.save_accumulation_frame(
        frame,
        group_index=1,
        raw_index=1,
    )

    for path in (tiff_path, accumulation_path):
        image, metadata = _read_tiff(path)
        expected_dtype = np.uint8 if image_format.bit_depth_saved == 8 else np.uint16
        assert image.dtype == np.dtype(expected_dtype)
        assert {
            key: metadata[key]
            for key in ("bit_depth_sensor", "bit_depth_saved", "pixel_format", "alignment")
        } == image_format.to_dict()

    angle_session = storage.start_angle_scan_session(
        build_angle_scan_document_from_conditions(
            settings=AngleScanSettings(
                range_deg=0.5,
                interval_deg=0.5,
                direction="positive",
                settling_time_ms=0,
                return_to_start_after_scan=False,
                position_units_per_deg=31.25,
            ),
            conditions=[CaptureCondition(exposure_ms=10.0, gain=0)],
            image_format=image_format,
        )
    )
    angle_tiff_path = angle_session.save_frame(frame, 0.5)
    angle_accumulation_path = angle_session.save_accumulation_frame(
        frame,
        0.5,
        condition_index=1,
        raw_index=1,
    )
    for path in (angle_tiff_path, angle_accumulation_path):
        image, metadata = _read_tiff(path)
        expected_dtype = np.uint8 if image_format.bit_depth_saved == 8 else np.uint16
        assert image.dtype == np.dtype(expected_dtype)
        assert {
            key: metadata[key]
            for key in ("bit_depth_sensor", "bit_depth_saved", "pixel_format", "alignment")
        } == image_format.to_dict()

    with (angle_session.session_dir / "scan.json").open(encoding="utf-8") as file:
        scan = json.load(file)
    assert scan["schema_version"] == 1
    assert scan["image_format"] == image_format.to_dict()
