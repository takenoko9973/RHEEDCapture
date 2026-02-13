from pathlib import Path

import numpy as np
import tifffile


class DataManager:
    """ファイルI/Oおよびディレクトリ構造を管理するクラス"""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def create_experiment_dir(self, date_str: str) -> Path:
        """実験日フォルダを作成する。同名が存在する場合は -2, -3 と枝番を付与する。

        Args:
            date_str (str): 日付文字列 (例: '260213')

        Returns:
            Path: 作成された実験フォルダのパス

        """
        target_dir = self.root_dir / date_str

        if not target_dir.exists():
            target_dir.mkdir(parents=True)
            return target_dir

        # 既に存在する場合は枝番を探索
        counter = 2
        while True:
            branch_dir = self.root_dir / f"{date_str}-{counter}"
            if not branch_dir.exists():
                branch_dir.mkdir(parents=True)
                return branch_dir
            counter += 1

    def create_image_dir(self, experiment_dir: Path, image_number: int) -> Path:
        """実験フォルダ内に写真フォルダ (image_001 など) を作成する。"""
        img_dir = experiment_dir / f"image_{image_number:03d}"
        img_dir.mkdir(parents=True, exist_ok=True)
        return img_dir

    def save_tiff(self, file_path: Path, image_data: np.ndarray, metadata: dict) -> None:
        """16bit画像データを非圧縮TIFFとして保存し、メタデータをImageDescriptionに埋め込む。
        画像データには一切の加工を行わない。

        Args:
            file_path (Path): 保存先パス
            image_data (np.ndarray): センサ生データ (uint16)
            metadata (dict): 埋め込む辞書データ

        """
        # tifffileを使用して、非圧縮かつメタデータ付きで保存
        tifffile.imwrite(file_path, image_data, photometric="minisblack", metadata=metadata)
