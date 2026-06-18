import shutil
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest

from rheed_capture.data_formats.angle_scan_document import (
    AngleScanDocument,
    AngleScanDocumentSettings,
    CaptureCondition,
)
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage


@pytest.fixture
def local_temp_root() -> Generator[Path, None, None]:
    root = Path.cwd() / ".test_tmp" / f"storage_sync_{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def test_next_sequence_is_based_on_max_image_suffix(local_temp_root: Path) -> None:
    storage = ExperimentStorage(local_temp_root)
    exp_dir = local_temp_root / storage.get_current_experiment_dir().name
    (exp_dir / "image_001").mkdir(parents=True)
    (exp_dir / "image_003").mkdir()
    (exp_dir / "image_007").mkdir()

    storage.refresh_sequence_counter_from_disk()

    assert storage.get_next_sequence_dir_name() == "image_008"


def test_next_angle_scan_is_based_on_max_scan_suffix(local_temp_root: Path) -> None:
    storage = ExperimentStorage(local_temp_root)
    exp_dir = local_temp_root / storage.get_current_experiment_dir().name
    (exp_dir / "angle_scan_001").mkdir(parents=True)
    (exp_dir / "angle_scan_003").mkdir()
    (exp_dir / "angle_scan_007").mkdir()

    storage.refresh_capture_counters_from_disk()

    assert storage.get_next_angle_scan_dir_name() == "angle_scan_008"


def test_refresh_reflects_deleted_max_directory(local_temp_root: Path) -> None:
    storage = ExperimentStorage(local_temp_root)
    exp_dir = local_temp_root / storage.get_current_experiment_dir().name
    (exp_dir / "image_001").mkdir(parents=True)
    (exp_dir / "image_005").mkdir()

    storage.refresh_sequence_counter_from_disk()
    assert storage.get_next_sequence_dir_name() == "image_006"

    (exp_dir / "image_005").rmdir()
    storage.refresh_sequence_counter_from_disk()

    assert storage.get_next_sequence_dir_name() == "image_002"


def test_refresh_reflects_deleted_max_angle_scan_directory(local_temp_root: Path) -> None:
    storage = ExperimentStorage(local_temp_root)
    exp_dir = local_temp_root / storage.get_current_experiment_dir().name
    (exp_dir / "angle_scan_001").mkdir(parents=True)
    (exp_dir / "angle_scan_005").mkdir()

    storage.refresh_capture_counters_from_disk()
    assert storage.get_next_angle_scan_dir_name() == "angle_scan_006"

    (exp_dir / "angle_scan_005").rmdir()
    storage.refresh_capture_counters_from_disk()

    assert storage.get_next_angle_scan_dir_name() == "angle_scan_002"


def test_start_new_sequence_uses_disk_rescan_before_assigning(local_temp_root: Path) -> None:
    storage = ExperimentStorage(local_temp_root)
    exp_dir = local_temp_root / storage.get_current_experiment_dir().name
    (exp_dir / "image_001").mkdir(parents=True)
    (exp_dir / "image_002").mkdir()

    # 実行直前に外部要因で増えたフォルダを想定
    (exp_dir / "image_005").mkdir()

    storage.start_new_sequence()

    assert storage.get_current_sequence_dir().name == "image_006"
    assert storage.get_current_sequence_dir().exists()


def test_start_new_angle_scan_uses_disk_rescan_before_assigning(
    local_temp_root: Path,
) -> None:
    storage = ExperimentStorage(local_temp_root)
    exp_dir = local_temp_root / storage.get_current_experiment_dir().name
    (exp_dir / "angle_scan_001").mkdir(parents=True)
    (exp_dir / "angle_scan_002").mkdir()

    # 実行直前に外部要因で増えたフォルダを想定
    (exp_dir / "angle_scan_005").mkdir()

    scan_id, scan_dir = storage.start_new_angle_scan(_scan_document())

    assert scan_id == "as006"
    assert scan_dir.name == "angle_scan_006"
    assert scan_dir.exists()


def _scan_document() -> AngleScanDocument:
    return AngleScanDocument(
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
