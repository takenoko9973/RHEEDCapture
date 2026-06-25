from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

from rheed_capture.data_formats.recording import RecordingFrameRow
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage


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
            exposure_ms=50.0,
            gain=0,
            filename=session.build_frame_path(1).name,
        )

        saved_count = session.append_saved_frame(row, 3.25)
        session.mark_cancelled()

        assert saved_count == 1
        with (Path(session.session_dir) / "frames.csv").open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))

        assert rows[0]["frame_index"] == "1"
        assert rows[0]["target_elapsed_ms"] == "0.000"
        assert rows[0]["actual_elapsed_ms"] == "2.500"
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
