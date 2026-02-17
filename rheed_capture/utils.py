import math
from collections.abc import Callable


def round_sig_figs(value: float, sig_figs: int = 2) -> float:
    """
    指定された有効数字の桁数で四捨五入を行う。

    Args:
        value (float): 四捨五入したい数値
        sig_figs (int, optional): 有効数字の桁数. デフォルトは2.

    Returns:
        float: 有効数字で丸められた数値

    """
    if value == 0.0 or math.isnan(value) or math.isinf(value):
        return value

    # 数値のオーダー（桁の大きさ）を常用対数で求める
    # 例: 123.4 -> オーダー2, 0.0123 -> オーダー-2
    order_of_magnitude = math.floor(math.log10(abs(value)))

    # 組み込み関数 round(値, 小数点以下の桁数) に渡すための桁数を計算
    # 有効数字が2桁でオーダーが2(100の位)の場合、10の位で丸めるため round(..., -1) となる
    round_digits = sig_figs - 1 - order_of_magnitude

    return round(value, round_digits)


def parse_numbers[T: (int, float)](
    data_str: str, dtype: Callable[[str], T], sep: str = ","
) -> list[T]:
    """カンマ区切りの文字列を指定の型に変換"""
    return [dtype(x.strip()) for x in data_str.split(sep)]
