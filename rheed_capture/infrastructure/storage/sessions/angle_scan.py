from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from rheed_capture.data_formats.frame_metadata import AngleScanFrameMetadata
from rheed_capture.data_formats.storage_naming import (
    ANGLE_DIR_PATTERN,
    ANGLE_SCAN_TIFF_COMPRESSION,
    ANGLE_SCAN_TIFF_FILENAME_PATTERN,
)
from rheed_capture.infrastructure.storage.tiff_writer import TiffWriter

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np

    from rheed_capture.application.capture.frame_capturer import CapturedFrame
    from rheed_capture.data_formats.angle_scan_document import AngleScanDocument

JST = ZoneInfo("Asia/Tokyo")


class AngleScanSession:
    """1つのAngle Scanディレクトリ内のscan.jsonと角度別TIFF保存を担当する。"""

    def __init__(
        self,
        session_dir: Path,
        *,
        scan_id: str,
        scan_document: AngleScanDocument,
        tiff_writer: type[TiffWriter] = TiffWriter,
    ) -> None:
        """Angle Scanディレクトリとscan.json作成に必要な情報を保持する。"""
        self.session_dir = session_dir
        self.scan_id = scan_id
        self.tiff_writer = tiff_writer
        self.scan_document = self._prepare_document(scan_document)
        self._write_scan_document()

    @property
    def dir_name(self) -> str:
        """UI表示や完了通知に使うSessionディレクトリ名を返す。"""
        return self.session_dir.name

    def _prepare_document(self, scan_document: AngleScanDocument) -> AngleScanDocument:
        """Storage側で確定したscan_idと作成時刻を保存モデルへ反映する。"""
        document = scan_document.with_scan_id(self.scan_id)
        if not document.created_at:
            document = document.with_created_at(datetime.now(JST).isoformat())

        return document

    def _write_scan_document(self) -> None:
        """`scan.json` をAngle Scan Session直下へ保存する。"""
        with (self.session_dir / "scan.json").open("w", encoding="utf-8") as f:
            json.dump(self.scan_document.to_dict(), f, ensure_ascii=False, indent=2)

    def save_frame(self, captured_frame: CapturedFrame, target_angle_deg: float) -> Path:
        """CapturedFrameと目標角度から保存メタデータを作り、Raw画像を保存する。"""
        metadata = AngleScanFrameMetadata(
            scan_id=self.scan_id,
            target_angle_deg=target_angle_deg,
            exposure_ms=captured_frame.condition.exposure_ms,
            gain=captured_frame.condition.gain,
            timestamp=captured_frame.timestamp,
        )
        return self.save_raw_frame(
            captured_frame.image,
            target_angle_deg,
            captured_frame.condition.exposure_ms,
            captured_frame.condition.gain,
            metadata.to_dict(),
        )

    def save_raw_frame(
        self,
        image_data: np.ndarray,
        target_angle_deg: float,
        exposure_ms: float,
        gain: float,
        metadata: dict,
    ) -> Path:
        """角度別ディレクトリとAngle Scan TIFFファイル名を作って保存する。"""
        if not self.session_dir.exists():
            msg = "角度走査が開始されていません。"
            raise RuntimeError(msg)

        angle_dir = self.session_dir / self.format_angle_dir_name(target_angle_deg)
        angle_dir.mkdir(parents=True, exist_ok=True)

        filename = self.format_angle_scan_filename(
            scan_id=self.scan_id,
            target_angle_deg=target_angle_deg,
            exposure_ms=exposure_ms,
            gain=gain,
        )
        file_path = angle_dir / filename
        if file_path.exists():
            msg = f"同名の角度走査TIFFが既に存在します: {file_path}"
            raise FileExistsError(msg)

        self.tiff_writer.save(
            file_path,
            image_data,
            metadata,
            compression=ANGLE_SCAN_TIFF_COMPRESSION,
        )
        return file_path

    @staticmethod
    def format_angle_dir_name(angle_deg: float) -> str:
        """Angle Scanの角度別サブディレクトリ名を生成する。"""
        return ANGLE_DIR_PATTERN.format(angle_deg=angle_deg)

    @staticmethod
    def format_angle_scan_filename(
        scan_id: str,
        target_angle_deg: float,
        exposure_ms: float,
        gain: float,
    ) -> str:
        """Angle ScanのTIFFファイル名を生成する。"""
        return ANGLE_SCAN_TIFF_FILENAME_PATTERN.format(
            scan_id=scan_id,
            angle_deg=target_angle_deg,
            exposure_ms=exposure_ms,
            gain=gain,
        )
