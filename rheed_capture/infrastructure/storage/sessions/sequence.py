from __future__ import annotations

from typing import TYPE_CHECKING

from rheed_capture.data_formats.frame_metadata import SequenceFrameMetadata
from rheed_capture.infrastructure.storage.tiff_writer import TiffWriter

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np

    from rheed_capture.application.capture.frame_capturer import CapturedFrame


class SequenceSession:
    """1つのSequence撮影ディレクトリ内のファイル名生成とTIFF保存を担当する。"""

    def __init__(
        self,
        session_dir: Path,
        *,
        experiment_dir_name: str,
        sequence_number: int,
        tiff_writer: type[TiffWriter] = TiffWriter,
    ) -> None:
        self.session_dir = session_dir
        self.experiment_dir_name = experiment_dir_name
        self.sequence_number = sequence_number
        self.tiff_writer = tiff_writer

    @property
    def dir_name(self) -> str:
        """UI表示や完了通知に使うSessionディレクトリ名を返す。"""
        return self.session_dir.name

    def save_frame(self, captured_frame: CapturedFrame) -> Path:
        """CapturedFrameから互換メタデータを作り、Raw画像を保存する。"""
        metadata = SequenceFrameMetadata(
            exposure_ms=captured_frame.condition.exposure_ms,
            gain=captured_frame.condition.gain,
            timestamp=captured_frame.timestamp,
        )
        return self.save_raw_frame(
            captured_frame.image,
            captured_frame.condition.exposure_ms,
            captured_frame.condition.gain,
            metadata.to_dict(),
        )

    def save_raw_frame(
        self,
        image_data: np.ndarray,
        exposure_ms: float,
        gain: float,
        metadata: dict,
    ) -> Path:
        """既存解析側が期待するSequence TIFFファイル名で保存する。"""
        if not self.session_dir.exists():
            msg = "シーケンスが開始されていません。"
            raise RuntimeError(msg)

        filename = (
            f"{self.experiment_dir_name}-{self.sequence_number}_"
            f"expo{exposure_ms:g}_gain{gain:g}.tiff"
        )
        file_path = self.session_dir / filename
        self.tiff_writer.save(file_path, image_data, metadata)
        return file_path
