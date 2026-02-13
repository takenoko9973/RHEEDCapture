import cv2
import numpy as np


class ImageProcessor:
    """RHEED画像処理を担当する静的クラス"""

    @staticmethod
    def to_8bit_preview(image_16bit: np.ndarray) -> np.ndarray:
        """16bitレンジの生データをプレビュー用に8bitへスケーリング"""
        return (image_16bit / 255.0).astype(np.uint8)

    @staticmethod
    def apply_double_clahe(image_16bit: np.ndarray) -> np.ndarray:
        """16bit画像に対してCLAHEを2段適用し、プレビュー用の8bit画像を生成する。

        Args:
            image_16bit (np.ndarray): カメラからの生データ (uint16, 12bit有効)

        Returns:
            np.ndarray: プレビュー用画像 (uint8)

        """
        clahe1 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        img_clahe1 = clahe1.apply(image_16bit)

        clahe2 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
        img_clahe2 = clahe2.apply(img_clahe1)

        return ImageProcessor.to_8bit_preview(img_clahe2)  # プレビュー用にuint8に変換
