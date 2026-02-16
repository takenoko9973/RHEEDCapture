import logging
import time

import numpy as np
from pypylon import genicam, pylon
from pypylon.pylon import GenericException, InstantCamera, TlFactory

logger = logging.getLogger(__name__)


class CameraDevice:
    """Baslerカメラの制御を行うハードウェアラッパークラス"""

    _camera: InstantCamera | None

    def __init__(self) -> None:
        self._camera = None

        self.converter = pylon.ImageFormatConverter()
        self.converter.OutputPixelFormat = pylon.PixelType_Mono16
        self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

    @property
    def camera(self) -> pylon.InstantCamera:
        """
        カメラインスタンスへ安全にアクセスするための内部プロパティ。
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

        def set_node_value(node_names: str | list[str], value: str | float | bool) -> None:
            if isinstance(node_names, str):
                node_names = [node_names]

            for node_name in node_names:
                try:
                    node = nodemap.GetNode(node_name)
                    if node is not None and genicam.IsWritable(node):
                        node.FromString(str(value))
                        return  # 設定に成功したら、残りの候補は試さずに終了する

                except genicam.LogicalErrorException:
                    # pypylon特有のエラー: ノードが存在しない場合はここに来るので無視して次へ
                    continue

                except Exception as e:  # noqa: BLE001
                    # その他の予期せぬエラー
                    logger.debug("Error accessing node '%s': %s", node_name, e)
                    continue

            logger.debug("Node '%s' is not writable or not found. Skipping.", node_name)

        # 必須フォーマット設定
        set_node_value("PixelFormat", "Mono12")

        # 自動機能の無効化
        set_node_value("ExposureAuto", "Off")
        set_node_value("GainAuto", "Off")

        # 画像補正の無効化
        set_node_value("Gamma", 1.0)
        # エミュレータでは"BlackLevel"しかないため、両方で設定するように対応
        set_node_value(["BlackLevelRaw", "BlackLevel"], 0)

        # デフォルトだと左右逆のため、補正
        set_node_value("ReverseX", True)

    def get_exposure_bounds(self) -> tuple[float, float]:
        """露光時間の最小・最大値(ms)を取得する"""
        # pylonはus単位なのでmsに変換して返す
        min_us = self.camera.ExposureTimeAbs.GetMin()
        max_us = self.camera.ExposureTimeAbs.GetMax()
        return (min_us / 1000.0, max_us / 1000.0)

    def get_gain_bounds(self) -> tuple[int, int]:
        """ゲインの最小・最大値を取得する"""
        min_gain = self.camera.GainRaw.GetMin()
        max_gain = self.camera.GainRaw.GetMax()
        return (min_gain, max_gain)

    def set_exposure(self, exposure_ms: float) -> None:
        """露光時間を設定 (単位: マイクロ秒)"""
        # Basler API はマイクロ秒(us)を要求するため、内部で1000倍する
        exposure_us = exposure_ms * 1000.0
        self.camera.ExposureTimeAbs.SetValue(exposure_us)

    def get_exposure(self) -> float:
        """現在の露光時間を取得 (ms)"""
        exposure_us = self.camera.ExposureTimeAbs.GetValue()
        return exposure_us / 1000.0

    def set_gain(self, gain: int) -> None:
        """ゲインを設定"""
        self.camera.GainRaw.SetValue(gain)

    def get_gain(self) -> float:
        """現在のゲインを取得"""
        return self.camera.GainRaw.GetValue()

    def start_preview_grab(self) -> None:
        """プレビュー用の画像取得を開始 (LatestImageOnly戦略)"""
        if self.is_connected() and not self.camera.IsGrabbing():
            self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

    def stop_grabbing(self) -> None:
        """画像取得を停止"""
        if self.is_connected() and self.camera.IsGrabbing():
            self.camera.StopGrabbing()

    def grab_one(self, timeout_ms: int) -> np.ndarray | None:
        """
        同期的に1枚の画像を取得する。

        Args:
            timeout_ms (int): タイムアウト時間(ms)

        Returns:
            np.ndarray: 画像データ (uint16)

        """
        if not self.is_connected():
            msg = "カメラが接続されていません。"
            raise RuntimeError(msg)

        # IsGrabbing() == True の時は呼べないため、事前に停止されていることを前提
        if self.camera.IsGrabbing():
            msg = "現在プレビュー実行中です。StopGrabbingを呼び出してください。"
            raise RuntimeError(msg)

        try:
            with self.camera.GrabOne(timeout_ms) as result:
                if result.GrabSucceeded():
                    image = self.converter.Convert(result)
                    return image.GetArray()

                return None

        except pylon.GenericException:
            logger.exception("プレビュー画像の取得中にエラーが発生しました")
            return None

    def retrieve_preview_frame(self, timeout_ms: int = 1000) -> np.ndarray | None:
        """
        プレビュー中(IsGrabbing == True)に最新のフレームを1枚取り出す。
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
            with self.camera.RetrieveResult(timeout_ms, pylon.TimeoutHandling_Return) as result:
                if result.GrabSucceeded():
                    image = self.converter.Convert(result)
                    return image.GetArray()

                return None

        except pylon.GenericException:
            logger.exception("プレビュー画像の取得中にエラーが発生しました")
            return None
