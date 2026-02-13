import logging
from typing import TYPE_CHECKING

import numpy as np
from pypylon import genicam, pylon
from pypylon.pylon import GenericException, InstantCamera, TlFactory

if TYPE_CHECKING:
    from pypylon.genicam import IEnumeration, IFloat

logger = logging.getLogger(__name__)


class CameraDevice:
    """Baslerカメラの制御を行うハードウェアラッパークラス"""

    _camera: InstantCamera | None

    def __init__(self) -> None:
        self._camera = None

    @property
    def camera(self) -> pylon.InstantCamera:
        """カメラインスタンスへ安全にアクセスするための内部プロパティ。
        接続されていない場合は RuntimeError。
        """
        if self._camera is None or not self._camera.IsOpen():
            msg = "カメラが接続されていません。"
            raise RuntimeError(msg)

        return self._camera

    def connect(self) -> None:
        """最初の利用可能なカメラに接続し、初期化設定を行う"""
        if self.is_connected():
            return

        try:
            tl_factory = TlFactory.GetInstance()
            devices = tl_factory.EnumerateDevices()
            if not devices:
                msg = "カメラが見つかりません。"
                raise RuntimeError(msg)

            # 最初に見つかったデバイスを作成
            self._camera = InstantCamera(tl_factory.CreateFirstDevice())
            self._camera.Open()

            self._apply_mandatory_settings()
            device_info = self.camera.GetDeviceInfo()
            logger.info("Connected to camera: %s", device_info.GetModelName())

        except GenericException as e:
            msg = f"カメラへの接続に失敗しました: {e}"
            raise RuntimeError(msg) from e

    def disconnect(self) -> None:
        """カメラから切断する"""
        if self.is_connected():
            self.stop_grabbing()
            self.camera.Close()
            self._camera = None

    def is_connected(self) -> bool:
        return self._camera is not None and self._camera.IsOpen()

    def _apply_mandatory_settings(self) -> None:
        """仕様書に基づく強制初期化設定 (Rawデータ担保)"""
        # NodeMapを取得
        nodemap = self.camera.GetNodeMap()

        # ユーティリティ: Writableな場合のみ設定する関数 (エミュレータと実機の差分吸収のため)
        def set_enum(node_name: str, value: str) -> None:
            node: IEnumeration = nodemap.GetNode(node_name)
            if node is not None and genicam.IsWritable(node):
                node.SetValue(value)

        def set_float(node_name: str, value: float) -> None:
            node: IFloat = nodemap.GetNode(node_name)
            if node is not None and genicam.IsWritable(node):
                node.SetValue(value)

        # 必須フォーマット設定
        set_enum("PixelFormat", "Mono16")

        # 自動機能の無効化
        set_enum("ExposureAuto", "Off")
        set_enum("GainAuto", "Off")

        # 画像補正の無効化
        set_float("Gamma", 1.0)
        set_float("BlackLevel", 0.0)

    def set_exposure(self, exposure_us: float) -> None:
        """露光時間を設定 (単位: マイクロ秒)"""
        if self.is_connected() and genicam.IsWritable(self.camera.ExposureTime):
            self.camera.ExposureTime.SetValue(exposure_us)

    def set_gain(self, gain: float) -> None:
        """ゲインを設定"""
        if self.is_connected() and genicam.IsWritable(self.camera.Gain):
            self.camera.Gain.SetValue(gain)

    def start_preview_grab(self) -> None:
        """プレビュー用の画像取得を開始 (LatestImageOnly戦略)"""
        if self.is_connected() and not self.camera.IsGrabbing():
            self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

    def stop_grabbing(self) -> None:
        """画像取得を停止"""
        if self.is_connected() and self.camera.IsGrabbing():
            self.camera.StopGrabbing()

    def grab_one(self, timeout_ms: int) -> np.ndarray:
        """同期的に1枚の画像を取得する。

        Args:
            timeout_ms (int): タイムアウト時間(ms)

        Returns:
            np.ndarray: 画像データ (uint16)

        """
        if not self.is_connected():
            msg = "カメラが接続されていません。"
            raise RuntimeError(msg)

        # GrabOne はカメラが IsGrabbing() == True の時は呼べないため、
        # 事前に停止されていることを前提とする。
        if self.camera.IsGrabbing():
            msg = "現在プレビュー実行中です。StopGrabbingを呼び出してください。"
            raise RuntimeError(msg)

        grab_result = self.camera.GrabOne(timeout_ms)

        try:
            if grab_result.GrabSucceeded():
                return grab_result.GetArray()

            msg = f"Grab failed: {grab_result.GetErrorDescription()}"
            raise RuntimeError(msg)

        finally:
            grab_result.Release()

    def retrieve_preview_frame(self, timeout_ms: int = 1000) -> np.ndarray | None:
        """プレビュー中(IsGrabbing == True)に最新のフレームを1枚取り出す。
        UIスレッドをブロックしないよう、タイムアウト時はNoneを返す。

        Args:
            timeout_ms (int): タイムアウト時間(ms)

        Returns:
            np.ndarray | None: 画像データ(uint16)。取得失敗・タイムアウト時はNone

        """
        if not self.is_connected() or not self.camera.IsGrabbing():
            return None

        try:
            # TimeoutHandling_Return で、タイムアウト時に例外ではなく無効なResultを返すようにする
            grab_result = self.camera.RetrieveResult(timeout_ms, pylon.TimeoutHandling_Return)

            img_data = grab_result.GetArray() if grab_result.GrabSucceeded() else None
            grab_result.Release()
            return img_data

        except pylon.GenericException:
            logger.exception("プレビュー画像の取得中にエラーが発生しました")
            return None
