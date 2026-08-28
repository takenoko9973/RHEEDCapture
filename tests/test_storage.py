import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import cast
from unittest.mock import patch
from zoneinfo import ZoneInfo

import imagecodecs
import numpy as np
import tifffile

from rheed_capture.application.capture.frame_capturer import CapturedFrame, CaptureTiming
from rheed_capture.application.ports.camera import FrameReadback, ImageFormatSnapshot
from rheed_capture.data_formats.angle_scan_document import (
    AngleScanDocument,
    AngleScanDocumentSettings,
    AngleScanStorageFormat,
    CaptureCondition,
    CaptureExecutionSettings,
)
from rheed_capture.data_formats.storage_naming import (
    ANGLE_DIR_PATTERN,
    ANGLE_SCAN_TIFF_FILENAME_PATTERN,
)
from rheed_capture.domain.capture_condition import CaptureCondition as DomainCaptureCondition
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage
from rheed_capture.infrastructure.storage.tiff_writer import TiffWriter

JST = ZoneInfo("Asia/Tokyo")
_IMAGE_FORMAT_12 = ImageFormatSnapshot(12, 16, "Mono12Packed", "MsbAligned")


def test_tiff_writer() -> None:
    """TiffWriter単体の書き込みテスト"""
    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = Path(temp_dir) / "test.tiff"
        data = np.ones((10, 10), dtype=np.uint16)
        meta = {"test_key": "test_value"}

        TiffWriter.save(file_path, data, meta)

        assert file_path.exists()
        with tifffile.TiffFile(file_path) as tif:
            assert np.array_equal(tif.asarray(), data)
            page = tif.pages[0]
            assert isinstance(page, tifffile.TiffPage)

            loaded_meta = json.loads(page.tags["ImageDescription"].value)
            assert loaded_meta["test_key"] == "test_value"


def test_tiff_writer_passes_fixed_zlib_settings() -> None:
    """zlib保存時にlevel 6とpredictor OFFをTIFF writerへ渡す。"""
    with patch("rheed_capture.infrastructure.storage.tiff_writer.tifffile.imwrite") as imwrite:
        TiffWriter.save(
            Path("frame.tiff"),
            np.zeros((2, 2), dtype=np.uint16),
            {},
            compression="zlib",
        )

    kwargs = imwrite.call_args.kwargs
    assert kwargs["compression"] == "zlib"
    assert kwargs["compressionargs"] == {"level": 6}
    assert kwargs["predictor"] is False

    with patch("rheed_capture.infrastructure.storage.tiff_writer.tifffile.imwrite") as imwrite:
        TiffWriter.save(
            Path("frame.tiff"),
            np.zeros((2, 2), dtype=np.uint16),
            {},
            compression=None,
        )

    kwargs = imwrite.call_args.kwargs
    assert kwargs["compression"] is None
    assert kwargs["compressionargs"] is None
    assert kwargs["predictor"] is False


def test_tiff_writer_zlib_uses_imagecodecs_backend() -> None:
    """zlibのTIFF codecがimagecodecsの実装へ解決される。"""
    assert tifffile.TIFF.COMPRESSORS[8].__module__ == imagecodecs.__name__


def test_tiff_writer_zlib_round_trips_dark_and_bright_uint8_and_uint16_pixels() -> None:
    """暗い画像と明るい画像のRaw uint8/uint16画素を完全一致で復号する。"""
    images = {
        "uint8-dark": np.arange(64, dtype=np.uint8).reshape(8, 8),
        "uint8-bright": np.arange(255, 191, -1, dtype=np.uint8).reshape(8, 8),
        "uint16-dark": np.arange(64, dtype=np.uint16).reshape(8, 8),
        "uint16-bright": np.arange(65535, 65471, -1, dtype=np.uint16).reshape(8, 8),
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        for name, image in images.items():
            file_path = Path(temp_dir) / f"{name}.tiff"
            TiffWriter.save(file_path, image, {}, compression="zlib")

            with tifffile.TiffFile(file_path) as tif:
                page = cast("tifffile.TiffPage", tif.pages[0])
                loaded = tif.asarray()
                compression = page.tags["Compression"].value
                has_predictor = "Predictor" in page.tags

            assert compression == 8
            assert not has_predictor
            assert loaded.shape == image.shape
            assert loaded.dtype == image.dtype
            assert np.array_equal(loaded, image)
            assert loaded.tobytes(order="C") == image.tobytes(order="C")


def test_lazy_directory_creation() -> None:
    """初期化時にはフォルダが作成されず、シーケンス開始時に作成されるテスト"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(temp_dir)
        # この時点ではフォルダが存在しないはず
        assert not storage.get_current_experiment_dir().exists()

        # 撮影開始時に初めて作られる
        storage.start_sequence_session(image_format=_IMAGE_FORMAT_12)
        assert storage.get_current_experiment_dir().exists()
        assert storage.get_current_sequence_dir().exists()


def test_experiment_storage_save_sequence() -> None:
    """連番(image_001)とファイル名(yymmdd-n_expo...)の自動生成テスト"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(root_dir=temp_dir)

        # 1回目のシーケンス撮影開始
        session = storage.start_sequence_session(image_format=_IMAGE_FORMAT_12)
        assert storage.get_current_sequence_dir().name == "image_001"

        data = np.zeros((10, 10), dtype=np.uint16)
        meta = {"exposure_ms": 50}

        # 保存実行
        saved_path = session.save_raw_frame(data, exposure_ms=50, gain=0, metadata=meta)

        # ファイル名が {yymmdd}-{n}_expo{Exposure}_gain{Gain}.tiff になっているか
        expected_filename = f"{storage.date_str}-1_expo50_gain0.tiff"
        assert saved_path.name == expected_filename
        assert saved_path.exists()

        # ===

        # 2回目のシーケンス撮影開始
        session2 = storage.start_sequence_session(image_format=_IMAGE_FORMAT_12)
        assert storage.get_current_sequence_dir().name == "image_002"

        saved_path2 = session2.save_raw_frame(data, exposure_ms=2000, gain=1.5, metadata=meta)

        expected_filename2 = f"{storage.date_str}-2_expo2000_gain1.5.tiff"
        assert saved_path2.name == expected_filename2
        assert saved_path2.exists()


def test_sequence_tiff_round_trips_requested_condition_and_camera_readback() -> None:
    """Sequence TIFFで要求条件とcamera読戻し値を区別して保存する。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(root_dir=temp_dir)
        session = storage.start_sequence_session(image_format=_IMAGE_FORMAT_12)
        captured_frame = CapturedFrame(
            image=np.zeros((2, 2), dtype=np.uint16),
            condition=DomainCaptureCondition(exposure_ms=50.0, gain=1),
            readback=FrameReadback(
                exposure_ms=49.5,
                gain=2,
                camera_timestamp_ticks=987654,
                camera_timestamp_frequency_hz=125_000_000,
                source="camera",
            ),
            timing=CaptureTiming(
                trigger_issued_at=datetime.fromisoformat("2026-07-11T12:00:00+09:00"),
                trigger_issued_monotonic_sec=1.0,
            ),
            image_format=_IMAGE_FORMAT_12,
        )

        saved_path = session.save_frame(captured_frame)

        with tifffile.TiffFile(saved_path) as tif:
            page = tif.pages[0]
            assert isinstance(page, tifffile.TiffPage)
            metadata = json.loads(page.tags["ImageDescription"].value)

        assert metadata["timestamp"] == "2026-07-11T12:00:00+09:00"
        assert metadata["exposure_ms"] == 50.0
        assert metadata["gain"] == 1
        assert metadata["camera_exposure_ms"] == 49.5
        assert metadata["camera_gain"] == 2
        assert metadata["camera_timestamp_ticks"] == 987654
        assert metadata["camera_timestamp_frequency_hz"] == 125_000_000
        assert metadata["camera_timestamp_source"] == "camera"


def test_root_change_and_branch_detection() -> None:
    """ルート変更時に既存の yymmdd-n を正しく認識し、連番を引き継ぐテスト"""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        storage = ExperimentStorage(root)
        date_str = storage.date_str

        # ダミーの既存フォルダを作成: {yymmdd}-2 と、その中に image_005 を作る
        target_dir = root / f"{date_str}-2"
        target_dir.mkdir()
        (target_dir / "image_005").mkdir()

        # ルートを再設定してスキャンさせる
        storage.set_root_dir(root)

        # 既存の最大ブランチ(-2)を認識しているか
        assert storage.get_current_experiment_dir().name == f"{date_str}-2"

        # 次のシーケンスは image_006 になるはず
        storage.start_sequence_session(image_format=_IMAGE_FORMAT_12)
        assert storage.get_current_sequence_dir().name == "image_006"


def test_manual_branch_increment() -> None:
    """GUIから手動でブランチ(-n)を更新できるテスト"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(temp_dir)
        date_str = storage.date_str

        assert storage.get_current_experiment_dir().name == date_str

        storage.increment_branch()
        assert storage.get_current_experiment_dir().name == f"{date_str}-2"


def test_angle_scan_storage_uses_independent_counter_and_spec_names() -> None:
    """Angle Scanが独立番号と保存形式定数でSessionを作ることを確認する。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(temp_dir)
        data = np.zeros((10, 10), dtype=np.uint16)
        scan_document = AngleScanDocument(
            schema_version=1,
            scan_id="",
            created_at="",
            angle_scan=AngleScanDocumentSettings(
                coordinate="relative",
                reference="current_position_at_scan_start",
                range_deg=0.5,
                interval_deg=0.5,
                direction="positive",
                position_units_per_deg=31.25,
                capture_angles_deg=[0.0, 0.5],
                wait_after_move_ms=0,
                motor_speed_rpm=4.0,
                return_to_start=False,
            ),
            capture_conditions=[CaptureCondition(exposure_ms=10.0, gain=0)],
            image_format=_IMAGE_FORMAT_12,
        )

        storage.start_sequence_session(image_format=_IMAGE_FORMAT_12)
        scan_session = storage.start_angle_scan_session(scan_document)
        scan_id = scan_session.scan_id
        scan_dir = scan_session.session_dir

        assert storage.get_current_sequence_dir().name == "image_001"
        assert scan_id == "as001"
        assert scan_dir.name == "angle_scan_001"
        assert (scan_dir / "scan.json").exists()

        saved_path = scan_session.save_raw_frame(
            data,
            target_angle_deg=0.5,
            exposure_ms=10.0,
            gain=0,
            metadata={"capture_mode": "angle_scan"},
        )

        assert saved_path.parent.name == "angle+000.5"
        assert saved_path.name == "as001_angle+000.5_exp10_gain0.tiff"
        with (scan_dir / "scan.json").open(encoding="utf-8") as f:
            saved_scan = json.load(f)
        assert saved_scan["scan_id"] == "as001"
        assert saved_scan["capture"] == {
            "loop_order": ["angle", "condition"],
            "retry_limit": 3,
        }
        assert saved_scan["storage"] == {
            "angle_directory_format": ANGLE_DIR_PATTERN,
            "filename_format": ANGLE_SCAN_TIFF_FILENAME_PATTERN,
        }


def test_accumulation_storage_writes_raw_groups_without_changing_tiff_metadata() -> None:
    """蓄積時も各Rawを明示的なグループへ既存メタデータのまま保存する。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(temp_dir)
        captured_frame = CapturedFrame(
            image=np.full((2, 2), 40_000, dtype=np.uint16),
            condition=DomainCaptureCondition(exposure_ms=10.0, gain=2),
            readback=FrameReadback(
                exposure_ms=9.5,
                gain=3,
                camera_timestamp_ticks=123,
                camera_timestamp_frequency_hz=125_000_000,
                source="camera",
            ),
            timing=CaptureTiming(
                trigger_issued_at=datetime.fromisoformat("2026-07-11T12:00:00+09:00"),
                trigger_issued_monotonic_sec=1.0,
            ),
            image_format=_IMAGE_FORMAT_12,
        )

        sequence_session = storage.start_sequence_session(image_format=_IMAGE_FORMAT_12)
        sequence_regular_path = sequence_session.save_frame(captured_frame)
        sequence_paths = [
            sequence_session.save_accumulation_frame(
                captured_frame,
                group_index=1,
                raw_index=raw_index,
            )
            for raw_index in range(1, 11)
        ]
        sequence_path = sequence_paths[0]
        assert sequence_path.relative_to(sequence_session.session_dir).as_posix() == (
            "group_0001_expo10_gain2/raw_0001.tiff"
        )

        scan_document = AngleScanDocument(
            schema_version=1,
            scan_id="",
            created_at="",
            angle_scan=AngleScanDocumentSettings(
                coordinate="relative",
                reference="current_position_at_scan_start",
                range_deg=0.5,
                interval_deg=0.5,
                direction="positive",
                position_units_per_deg=31.25,
                capture_angles_deg=[0.0, 0.5],
                wait_after_move_ms=0,
                motor_speed_rpm=4.0,
                return_to_start=False,
            ),
            capture_conditions=[CaptureCondition(exposure_ms=10.0, gain=2)],
            image_format=_IMAGE_FORMAT_12,
            capture=CaptureExecutionSettings.for_accumulation(
                retry_limit=3,
                accumulation_frames=10,
            ),
            storage=AngleScanStorageFormat.for_accumulation(10),
        )
        angle_session = storage.start_angle_scan_session(scan_document)
        angle_regular_path = angle_session.save_frame(captured_frame, 0.5)
        angle_paths = [
            angle_session.save_accumulation_frame(
                captured_frame,
                0.5,
                condition_index=1,
                raw_index=raw_index,
            )
            for raw_index in range(1, 11)
        ]
        angle_path = angle_paths[0]
        assert angle_path.relative_to(angle_session.session_dir).as_posix() == (
            "angle+000.5/group_0001_exp10_gain2/raw_0001.tiff"
        )
        assert len(sequence_paths) == 10
        assert len(angle_paths) == 10
        assert all(path.exists() for path in [*sequence_paths, *angle_paths])

        with tifffile.TiffFile(sequence_path) as tif:
            assert np.array_equal(tif.asarray(), captured_frame.image)
            sequence_page = cast("tifffile.TiffPage", tif.pages[0])
            sequence_metadata = json.loads(sequence_page.tags["ImageDescription"].value)
        with tifffile.TiffFile(sequence_regular_path) as tif:
            sequence_regular_page = cast("tifffile.TiffPage", tif.pages[0])
            sequence_regular_metadata = json.loads(
                sequence_regular_page.tags["ImageDescription"].value
            )
        with tifffile.TiffFile(angle_path) as tif:
            assert np.array_equal(tif.asarray(), captured_frame.image)
            angle_page = cast("tifffile.TiffPage", tif.pages[0])
            angle_metadata = json.loads(angle_page.tags["ImageDescription"].value)
        with tifffile.TiffFile(angle_regular_path) as tif:
            angle_regular_page = cast("tifffile.TiffPage", tif.pages[0])
            angle_regular_metadata = json.loads(
                angle_regular_page.tags["ImageDescription"].value
            )

        assert sequence_metadata == sequence_regular_metadata
        assert angle_metadata == angle_regular_metadata

        with (angle_session.session_dir / "scan.json").open(encoding="utf-8") as f:
            saved_scan = json.load(f)
        assert saved_scan["capture"] == {
            "loop_order": ["angle", "condition", "raw"],
            "retry_limit": 3,
            "accumulation_frames": 10,
        }
        assert saved_scan["storage"] == {
            "angle_directory_format": ANGLE_DIR_PATTERN,
            "group_directory_format": "group_{condition_index:04d}_exp{exposure_ms:g}_gain{gain:g}",
            "raw_filename_format": "raw_{raw_index:04d}.tiff",
        }


def test_angle_scan_counter_uses_max_suffix_without_reuse() -> None:
    """既存Angle Scan最大番号の次番号を使い、番号を再利用しない。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(temp_dir)
        exp_dir = storage.get_current_experiment_dir()
        exp_dir.mkdir(parents=True)
        (exp_dir / "angle_scan_001").mkdir()
        (exp_dir / "angle_scan_004").mkdir()

        storage.refresh_angle_scan_counter_from_disk()

        assert storage.get_next_angle_scan_dir_name() == "angle_scan_005"
