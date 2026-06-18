import logging
from pathlib import Path

import numpy as np
import tifffile

logger = logging.getLogger(__name__)


class TiffWriter:
    @staticmethod
    def save(file_path: Path, image_data: np.ndarray, metadata: dict) -> None:
        try:
            tifffile.imwrite(file_path, image_data, photometric="minisblack", metadata=metadata)
        except Exception:
            logger.exception("TIFF保存に失敗しました (%s)", file_path)
            raise
