import json
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import tifffile

from rheed_capture.models.io.storage import ExperimentStorage, TiffWriter

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
        storage.start_new_sequence()
        assert storage.get_current_experiment_dir().exists()
        assert storage.get_current_sequence_dir().exists()


def test_experiment_storage_save_sequence() -> None:
    """連番(image_001)とファイル名(yymmdd-n_expo...)の自動生成テスト"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(root_dir=temp_dir)

        # 1回目のシーケンス撮影開始
        storage.start_new_sequence()
        assert storage.get_current_sequence_dir().name == "image_001"

        data = np.zeros((10, 10), dtype=np.uint16)
        meta = {"exposure_ms": 50}

        # 保存実行
        saved_path = storage.save_frame(data, exposure_ms=50, gain=0, metadata=meta)

        # ファイル名が {yymmdd}-{n}_expo{Exposure}_gain{Gain}.tiff になっているか
        expected_filename = f"{storage.date_str}-1_expo50_gain0.tiff"
        assert saved_path.name == expected_filename
        assert saved_path.exists()

        # ===

        # 2回目のシーケンス撮影開始
        storage.start_new_sequence()
        assert storage.get_current_sequence_dir().name == "image_002"

        saved_path2 = storage.save_frame(data, exposure_ms=2000, gain=1.5, metadata=meta)

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
        storage.start_new_sequence()
        assert storage.get_current_sequence_dir().name == "image_006"


def test_manual_branch_increment() -> None:
    """GUIから手動でブランチ(-n)を更新できるテスト"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(temp_dir)
        date_str = storage.date_str

        assert storage.get_current_experiment_dir().name == date_str

        storage.increment_branch()
        assert storage.get_current_experiment_dir().name == f"{date_str}-2"
