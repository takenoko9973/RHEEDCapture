import shutil
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest

from rheed_capture.models.io.storage import ExperimentStorage


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
