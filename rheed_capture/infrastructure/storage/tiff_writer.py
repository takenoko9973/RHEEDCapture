import logging
from pathlib import Path

import numpy as np
import tifffile

logger = logging.getLogger(__name__)


class TiffWriter:
    """TIFF保存ライブラリ呼び出しを集約する薄いAdapter。"""

    @staticmethod
    def save(
        file_path: Path,
        image_data: np.ndarray,
        metadata: dict,
        *,
        compression: str | None = None,
    ) -> None:
        """画像配列とメタデータをTIFFファイルへ保存する。"""
        try:
            tifffile.imwrite(
                file_path,
                image_data,
                photometric="minisblack",
                metadata=metadata,
                compression=compression,
            )
        except Exception:
            logger.exception("TIFF保存に失敗しました (%s)", file_path)
            raise
