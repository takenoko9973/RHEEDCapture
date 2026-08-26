from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from rheed_capture.data_formats.angle_scan_document import (
    AngleScanDocument,
    AngleScanDocumentSettings,
    CaptureCondition,
)
from rheed_capture.data_formats.recording import RecordingFrameRow
from rheed_capture.data_formats.storage_naming import (
    ANGLE_SCAN_TIFF_COMPRESSION,
    SEQUENCE_TIFF_COMPRESSION,
)
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage
from rheed_capture.infrastructure.storage.tiff_writer import TiffWriter


def test_recording_session_creates_record_dirs_json_csv_and_filenames() -> None:
    """RecordingSession作成時にdir、JSON、CSV、TIFF名が決まることを確認する。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(temp_dir)

        session = storage.start_recording_session(
            sample_name="STO",
            exposure_ms=50.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=300.0,
            duration_ms=None,
        )

        assert session.dir_name == "record-1"
        assert session.build_frame_path(1).name == f"STO_{storage.date_str}_rec-1_00001.tiff"
        assert session.build_frame_path(99999).name.endswith("_99999.tiff")
        assert (Path(session.session_dir) / "recording.json").exists()
        assert (Path(session.session_dir) / "frames.csv").exists()

        with (Path(session.session_dir) / "recording.json").open(encoding="utf-8") as f:
            document = json.load(f)

        assert document["status"] == "running"
        assert document["timing"]["duration_ms"] is None
        assert document["storage"]["tiff_compression"] == "zlib"
        session.mark_completed()

        next_session = storage.start_recording_session(
            sample_name="STO",
            exposure_ms=50.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=300.0,
            duration_ms=1000.0,
        )
        assert next_session.dir_name == "record-2"
        next_session.mark_completed()


def test_recording_session_appends_csv_after_saved_and_marks_cancelled() -> None:
    """保存完了後にCSVへ追記し、キャンセル状態をJSONへ保存する。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(temp_dir)
        session = storage.start_recording_session(
            sample_name="STO",
            exposure_ms=50.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=300.0,
            duration_ms=1000.0,
        )
        row = RecordingFrameRow(
            frame_index=1,
            target_elapsed_ms=0.0,
            actual_elapsed_ms=2.5,
            timestamp="2026-06-25T15:00:00+09:00",
            camera_timestamp_ticks=123456,
            camera_timestamp_frequency_hz=125_000_000,
            camera_timestamp_source="camera",
            exposure_ms=50.0,
            gain=0,
            camera_exposure_ms=49.5,
            camera_gain=1,
            filename=session.build_frame_path(1).name,
            save_queue_depth=7,
        )

        saved_count = session.append_saved_frame(row, 3.25)
        session.mark_cancelled()

        assert saved_count == 1
        with (Path(session.session_dir) / "frames.csv").open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))

        assert rows[0]["frame_index"] == "1"
        assert rows[0]["target_elapsed_ms"] == "0.000"
        assert rows[0]["actual_elapsed_ms"] == "2.500"
        assert rows[0]["camera_exposure_ms"] == "49.5"
        assert rows[0]["camera_gain"] == "1"
        assert rows[0]["camera_timestamp_ticks"] == "123456"
        assert rows[0]["camera_timestamp_frequency_hz"] == "125000000"
        assert rows[0]["camera_timestamp_source"] == "camera"
        assert rows[0]["save_queue_depth"] == "7"
        assert rows[0]["save_elapsed_ms"] == "3.250"

        with (Path(session.session_dir) / "recording.json").open(encoding="utf-8") as f:
            document = json.load(f)

        assert document["status"] == "cancelled"
        assert document["result"]["saved_frames"] == 1


def test_recording_counter_uses_existing_record_suffixes() -> None:
    """既存record最大suffixから次Recording番号を決めることを確認する。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(temp_dir)
        exp_dir = storage.get_current_experiment_dir()
        (exp_dir / "record-1").mkdir(parents=True)
        (exp_dir / "record-4").mkdir()

        storage.refresh_recording_counter_from_disk()

        assert storage.get_next_recording_dir_name() == "record-5"


def test_accumulation_recording_uses_group_raw_paths_and_relative_csv_filename() -> None:
    """積算Recordingだけがgroup配下Raw保存形式とそのJSON契約を使う。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(temp_dir)
        session = storage.start_recording_session(
            sample_name="STO",
            exposure_ms=50.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=300.0,
            duration_ms=None,
            accumulation_frames=2,
        )
        raw_path = session.build_accumulation_frame_path(1, 2)
        assert raw_path.relative_to(session.session_dir).as_posix() == "group_000001/raw_0002.tiff"

        session.append_saved_frame(
            RecordingFrameRow(
                frame_index=2,
                target_elapsed_ms=None,
                actual_elapsed_ms=10.0,
                timestamp="2026-06-25T15:00:00+09:00",
                camera_timestamp_ticks=123456,
                camera_timestamp_frequency_hz=125_000_000,
                camera_timestamp_source="host",
                exposure_ms=50.0,
                gain=0,
                camera_exposure_ms=49.5,
                camera_gain=1,
                filename="group_000001/raw_0002.tiff",
                save_queue_depth=2,
            ),
            3.25,
        )
        session.mark_completed()

        with (Path(session.session_dir) / "frames.csv").open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        with (Path(session.session_dir) / "recording.json").open(encoding="utf-8") as f:
            document = json.load(f)

        assert rows[0]["target_elapsed_ms"] == ""
        assert rows[0]["filename"] == "group_000001/raw_0002.tiff"
        assert document["storage"] == {
            "folder_name": "record-1",
            "tiff_compression": "zlib",
            "group_directory_format": "group_{group_index:06d}",
            "raw_filename_format": "raw_{raw_index:04d}.tiff",
        }


@pytest.mark.parametrize(
    ("compression_enabled", "expected_compression"),
    [(True, "zlib"), (False, None)],
)
def test_recording_session_records_actual_tiff_compression(
    compression_enabled: bool,
    expected_compression: str | None,
) -> None:
    """Recording JSONの圧縮状態が実際の設定と一致する。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(temp_dir)
        session = storage.start_recording_session(
            sample_name="STO",
            exposure_ms=50.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=100.0,
            duration_ms=None,
            tiff_compression_enabled=compression_enabled,
        )

        with session.recording_json_path.open(encoding="utf-8") as f:
            document = json.load(f)

        assert document["storage"]["tiff_compression"] == expected_compression
        session.mark_completed()


def test_sequence_and_angle_scan_use_zlib_compression() -> None:
    """SequenceとAngle ScanはRecording設定に関係なくzlibを渡す。"""
    assert SEQUENCE_TIFF_COMPRESSION == "zlib"
    assert ANGLE_SCAN_TIFF_COMPRESSION == "zlib"

    with patch.object(TiffWriter, "save") as save:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = ExperimentStorage(temp_dir)
            sequence_session = storage.start_sequence_session()
            sequence_session.save_raw_frame(
                np.zeros((2, 2), dtype=np.uint16),
                exposure_ms=10.0,
                gain=0,
                metadata={},
            )
            angle_session = storage.start_angle_scan_session(
                AngleScanDocument(
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
                )
            )
            angle_session.save_raw_frame(
                np.zeros((2, 2), dtype=np.uint16),
                target_angle_deg=0.5,
                exposure_ms=10.0,
                gain=0,
                metadata={},
            )

        assert [call.kwargs["compression"] for call in save.call_args_list] == [
            "zlib",
            "zlib",
        ]
