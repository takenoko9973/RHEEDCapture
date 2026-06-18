import cv2
import numpy as np


class ImageProcessor:
    @staticmethod
    def to_8bit_preview(image_16bit: np.ndarray) -> np.ndarray:
        return (image_16bit >> 8).astype(np.uint8)

    @staticmethod
    def apply_double_clahe(image_16bit: np.ndarray) -> np.ndarray:
        clahe1 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        img_clahe1 = clahe1.apply(image_16bit)

        clahe2 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
        img_clahe2 = clahe2.apply(img_clahe1)

        return ImageProcessor.to_8bit_preview(img_clahe2)
