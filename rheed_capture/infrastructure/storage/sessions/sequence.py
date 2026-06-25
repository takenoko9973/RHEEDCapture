from __future__ import annotations

from typing import TYPE_CHECKING

from rheed_capture.data_formats.frame_metadata import SequenceFrameMetadata
from rheed_capture.data_formats.storage_naming import (
    SEQUENCE_TIFF_COMPRESSION,
    SEQUENCE_TIFF_FILENAME_PATTERN,
)
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
        """Sequenceディレクトリと番号、TIFF writerを保持する。"""
        self.session_dir = session_dir
        self.experiment_dir_name = experiment_dir_name
        self.sequence_number = sequence_number
        self.tiff_writer = tiff_writer

    @property
    def dir_name(self) -> str:
        """UI表示や完了通知に使うSessionディレクトリ名を返す。"""
        return self.session_dir.name

    def save_frame(self, captured_frame: CapturedFrame) -> Path:
        """CapturedFrameから保存メタデータを作り、Raw画像を保存する。"""
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
        """SequenceのTIFFファイル名規則に従ってRaw画像を保存する。"""
        if not self.session_dir.exists():
            msg = "シーケンスが開始されていません。"
            raise RuntimeError(msg)

        filename = SEQUENCE_TIFF_FILENAME_PATTERN.format(
            experiment_dir_name=self.experiment_dir_name,
            sequence_number=self.sequence_number,
            exposure_ms=exposure_ms,
            gain=gain,
        )
        file_path = self.session_dir / filename
        self.tiff_writer.save(
            file_path,
            image_data,
            metadata,
            compression=SEQUENCE_TIFF_COMPRESSION,
        )
        return file_path
