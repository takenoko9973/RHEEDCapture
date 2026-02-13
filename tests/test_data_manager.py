import os
import json
import tempfile
import numpy as np
import tifffile
from pathlib import Path
from rheed_capture.core.data_manager import DataManager

def test_experiment_directory_creation():
    with tempfile.TemporaryDirectory() as temp_dir:
        dm = DataManager(root_dir=temp_dir)

        # 1回目の実験フォルダ生成
        dir1 = dm.create_experiment_dir("260213")
        assert dir1.name == "260213"
        assert dir1.exists()

        # 2回目の同日実験フォルダ生成 (枝番がつくこと)
        dir2 = dm.create_experiment_dir("260213")
        assert dir2.name == "260213-2"
        assert dir2.exists()

        # image_001 フォルダの生成チェック
        img_dir = dm.create_image_dir(dir2, 1)
        assert img_dir.name == "image_001"
        assert img_dir.exists()

def test_save_tiff_with_metadata():
    with tempfile.TemporaryDirectory() as temp_dir:
        dm = DataManager(root_dir=temp_dir)
        dummy_data = np.ones((100, 100), dtype=np.uint16) * 2048 # 12bit value

        meta = {
            "exposure_us": 10000,
            "gain": 0,
            "timestamp": "2026-02-13T12:00:00",
            "bit_depth_saved": 16,
            "bit_depth_sensor": 12
        }

        # 保存実行
        file_path = Path(temp_dir) / "test_image.tiff"
        dm.save_tiff(file_path, dummy_data, meta)

        # 保存されたファイルの検証
        assert file_path.exists()

        # tifffileで読み込み、メタデータ(ImageDescription)をパース
        with tifffile.TiffFile(file_path) as tif:
            loaded_data = tif.asarray()
            assert np.array_equal(loaded_data, dummy_data), "データが改変されていないこと"

            page = tif.pages[0]
            assert len(tif.pages) == 1, "Tiffファイルのページは1枚のみ"
            assert isinstance(page, tifffile.TiffPage), "ページデータが保存されているか確認"

            description = page.tags["ImageDescription"].value
            loaded_meta = json.loads(description)

            assert loaded_meta["exposure_us"] == 10000
            assert loaded_meta["bit_depth_sensor"] == 12
