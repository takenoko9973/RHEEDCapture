import cv2
import numpy as np

SENSOR_BIT_DEPTH_8 = 8
SENSOR_BIT_DEPTH_12 = 12


class ImageProcessor:
    @staticmethod
    def to_8bit_preview(
        image: np.ndarray,
        *,
        sensor_bit_depth: int = 12,
    ) -> np.ndarray:
        """センサbit depthに対応する表示用uint8画像へ変換する。"""
        if sensor_bit_depth == SENSOR_BIT_DEPTH_8:
            return np.asarray(image, dtype=np.uint8)
        if sensor_bit_depth != SENSOR_BIT_DEPTH_12:
            msg = "sensor_bit_depth must be 8 or 12."
            raise ValueError(msg)
        return (np.asarray(image) >> 8).astype(np.uint8)

    @staticmethod
    def apply_double_clahe(
        image: np.ndarray,
        *,
        sensor_bit_depth: int = 12,
    ) -> np.ndarray:
        """センサbit depthに合わせて2段CLAHEを適用する。"""
        if sensor_bit_depth == SENSOR_BIT_DEPTH_8:
            image_for_clahe = np.asarray(image, dtype=np.uint8)
        elif sensor_bit_depth == SENSOR_BIT_DEPTH_12:
            image_for_clahe = np.asarray(image)
        else:
            msg = "sensor_bit_depth must be 8 or 12."
            raise ValueError(msg)

        clahe1 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        img_clahe1 = clahe1.apply(image_for_clahe)

        clahe2 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
        img_clahe2 = clahe2.apply(img_clahe1)

        return ImageProcessor.to_8bit_preview(
            img_clahe2,
            sensor_bit_depth=sensor_bit_depth,
        )
