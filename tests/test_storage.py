import json
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import tifffile

from rheed_capture.data_formats.angle_scan_document import (
    AngleScanDocument,
    AngleScanDocumentSettings,
    CaptureCondition,
)
from rheed_capture.data_formats.storage_naming import (
    ANGLE_DIR_PATTERN,
    ANGLE_SCAN_TIFF_FILENAME_PATTERN,
)
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage
from rheed_capture.infrastructure.storage.tiff_writer import TiffWriter

JST = ZoneInfo("Asia/Tokyo")


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


def test_lazy_directory_creation() -> None:
    """初期化時にはフォルダが作成されず、シーケンス開始時に作成されるテスト"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(temp_dir)
        # この時点ではフォルダが存在しないはず
        assert not storage.get_current_experiment_dir().exists()

        # 撮影開始時に初めて作られる
        storage.start_sequence_session()
        assert storage.get_current_experiment_dir().exists()
        assert storage.get_current_sequence_dir().exists()


def test_experiment_storage_save_sequence() -> None:
    """連番(image_001)とファイル名(yymmdd-n_expo...)の自動生成テスト"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(root_dir=temp_dir)

        # 1回目のシーケンス撮影開始
        session = storage.start_sequence_session()
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
        session2 = storage.start_sequence_session()
        assert storage.get_current_sequence_dir().name == "image_002"

        saved_path2 = session2.save_raw_frame(data, exposure_ms=2000, gain=1.5, metadata=meta)

        expected_filename2 = f"{storage.date_str}-2_expo2000_gain1.5.tiff"
        assert saved_path2.name == expected_filename2
        assert saved_path2.exists()


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
        storage.start_sequence_session()
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
        )

        storage.start_sequence_session()
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
        assert saved_scan["storage"]["angle_directory_format"] == ANGLE_DIR_PATTERN
        assert saved_scan["storage"]["filename_format"] == ANGLE_SCAN_TIFF_FILENAME_PATTERN


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
