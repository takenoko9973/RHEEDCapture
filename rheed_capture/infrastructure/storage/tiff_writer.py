import logging
from pathlib import Path

import numpy as np
import tifffile

logger = logging.getLogger(__name__)

TIFF_ZLIB_COMPRESSION_LEVEL = 6


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
            compressionargs = (
                {"level": TIFF_ZLIB_COMPRESSION_LEVEL} if compression == "zlib" else None
            )
            tifffile.imwrite(
                file_path,
                image_data,
                photometric="minisblack",
                metadata=metadata,
                compression=compression,
                compressionargs=compressionargs,
                predictor=False,
            )
        except Exception:
            logger.exception("TIFF保存に失敗しました (%s)", file_path)
            raise
