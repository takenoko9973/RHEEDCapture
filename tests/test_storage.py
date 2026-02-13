import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import tifffile

from rheed_capture.core.storage import ExperimentStorage, TiffWriter

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


def test_experiment_storage_directory_creation() -> None:
    """ExperimentStorageのディレクトリと連番管理のテスト"""
    with tempfile.TemporaryDirectory() as temp_dir:
        # 1回目の起動 (今日のyymmddが作られる)
        storage1 = ExperimentStorage(root_dir=temp_dir)
        date_str = datetime.now(JST).strftime("%y%m%d")

        assert storage1.experiment_dir.name == date_str
        assert storage1.date_prefix == date_str

        # 2回目の起動をエミュレート (同日に別のExperimentStorageインスタンスを作成)
        storage2 = ExperimentStorage(root_dir=temp_dir)
        assert storage2.experiment_dir.name == f"{date_str}-2"


def test_experiment_storage_save_sequence() -> None:
    """連番(image_001)とファイル名(yymmdd-n_Exp...)の自動生成テスト"""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = ExperimentStorage(root_dir=temp_dir)

        # 1回目のシーケンス撮影開始
        storage.start_new_sequence()
        assert storage.current_sequence_dir is not None
        assert storage.current_sequence_dir.name == "image_001"

        data = np.zeros((10, 10), dtype=np.uint16)
        meta = {"exposure_ms": 50}

        # 保存実行 (パスの計算はStorage内部で行われる)
        saved_path = storage.save_frame(data, exposure_ms=50, gain=0, metadata=meta)

        # ファイル名が仕様通り {yymmdd}-{n}_expo{Exposure}_gain{Gain}.tiff になっているか
        expected_filename = f"{storage.date_prefix}-1_expo50_gain0.tiff"
        assert saved_path.name == expected_filename
        assert saved_path.exists()

        # 2回目のシーケンス撮影開始
        storage.start_new_sequence()
        assert storage.current_sequence_dir.name == "image_002"
        saved_path2 = storage.save_frame(data, exposure_ms=2000, gain=1.5, metadata=meta)

        expected_filename2 = f"{storage.date_prefix}-2_expo2000_gain1.5.tiff"  # 小数点切り捨て
        assert saved_path2.name == expected_filename2
