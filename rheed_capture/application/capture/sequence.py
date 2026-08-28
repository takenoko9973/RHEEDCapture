from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np

from rheed_capture.application.capture.frame_capturer import CapturedFrame, FrameCapture
from rheed_capture.application.ports.camera import (
    SENSOR_BIT_DEPTH_8,
    ImageFormatSnapshot,
)
from rheed_capture.domain.capture_condition import CaptureCondition

if TYPE_CHECKING:
    from rheed_capture.application.capture.cancellation import CancellationToken
    from rheed_capture.application.ports.storage import SequenceSession
ProgressCallback = Callable[[int, int, CaptureCondition], None]
FrameCallback = Callable[[CapturedFrame], None]


class SequenceCapture:
    """Sequence固有の撮影順序だけを担当するQt非依存の実行クラス。"""

    def __init__(
        self,
        frame_capturer: FrameCapture,
        session: SequenceSession,
        conditions: list[CaptureCondition],
        *,
        accumulation_frames: int = 1,
        trigger_wait_timeout_sec: float = 0,
        image_format: ImageFormatSnapshot,
    ) -> None:
        self.frame_capturer = frame_capturer
        self.session = session
        self.accumulation_frames = accumulation_frames
        self.trigger_wait_timeout_sec = trigger_wait_timeout_sec
        self.image_format = image_format
        # 呼び出し元のリスト変更が撮影中に影響しないよう、開始時点の条件をコピーする。
        self.conditions = list(conditions)
        if not self.conditions:
            # 空条件のまま進むと成功扱いで空セッションが作られるため、実行前に止める。
            msg = "撮影条件がありません。"
            raise ValueError(msg)
        if self.accumulation_frames <= 0:
            msg = "蓄積フレーム数は1以上にしてください。"
            raise ValueError(msg)

    @property
    def total_shots(self) -> int:
        """現在の条件リストから算出した総撮影枚数を返す。"""
        return len(self.conditions)

    def run(
        self,
        cancellation_token: CancellationToken,
        *,
        on_progress: ProgressCallback | None = None,
        on_frame_captured: FrameCallback | None = None,
    ) -> None:
        """全撮影条件を順に撮影・保存し、必要に応じて進捗とRawフレームを通知する。"""
        for shot_count, condition in enumerate(self.conditions, 1):
            cancellation_token.raise_if_cancelled()

            if on_progress is not None:
                on_progress(shot_count, self.total_shots, condition)

            if self.accumulation_frames == 1:
                # OFF/N=1では、単一フレーム用の保存先・ファイル名・メタデータ経路で保存する。
                # Trigger modeの判定はFrameCapturerへ集約し、Hardware時だけ共通待機
                # timeout・no retry規則を適用する。
                for captured_frame in self.frame_capturer.capture_group(
                    condition,
                    frame_count=1,
                    hardware_wait_timeout_sec=self.trigger_wait_timeout_sec,
                    cancellation_token=cancellation_token,
                ):
                    self.session.save_frame(captured_frame)

                    if on_frame_captured is not None:
                        on_frame_captured(captured_frame)
                continue

            accumulated_image: np.ndarray | None = None
            completed_frame: CapturedFrame | None = None
            for raw_index, captured_frame in enumerate(
                self.frame_capturer.capture_group(
                    condition,
                    frame_count=self.accumulation_frames,
                    hardware_wait_timeout_sec=self.trigger_wait_timeout_sec,
                    cancellation_token=cancellation_token,
                ),
                1,
            ):
                self.session.save_accumulation_frame(
                    captured_frame,
                    group_index=shot_count,
                    raw_index=raw_index,
                )
                accumulated_image = _accumulate_image(
                    accumulated_image,
                    captured_frame.image,
                )
                completed_frame = captured_frame

            if on_frame_captured is not None:
                if accumulated_image is None or completed_frame is None:
                    msg = "蓄積撮影でRawフレームを取得できませんでした。"
                    raise RuntimeError(msg)
                on_frame_captured(
                    CapturedFrame(
                        image=_clip_accumulated_image(
                            accumulated_image,
                            self.image_format,
                        ),
                        condition=completed_frame.condition,
                        readback=completed_frame.readback,
                        timing=completed_frame.timing,
                        image_format=self.image_format,
                    )
                )


def _accumulate_image(
    accumulated_image: np.ndarray | None,
    image: np.ndarray,
) -> np.ndarray:
    """Rawのuint16加算で途中の桁あふれを起こさない合計画像を返す。"""
    image_wide = np.asarray(image, dtype=np.uint64)
    if accumulated_image is None:
        return image_wide

    return accumulated_image + image_wide


def _clip_accumulated_image(
    accumulated_image: np.ndarray,
    image_format: ImageFormatSnapshot,
) -> np.ndarray:
    """表示通知直前に合計画像を保存形式のdtype範囲へclipする。"""
    output_dtype = (
        np.uint8 if image_format.bit_depth_sensor == SENSOR_BIT_DEPTH_8 else np.uint16
    )
    return np.clip(
        accumulated_image,
        0,
        np.iinfo(output_dtype).max,
    ).astype(output_dtype)
