from collections.abc import Iterable

GridShape = tuple[int, int]

# 1xN / Nx1 を許可するため、最小値は 1 とする。
MIN_GRID_LINES = 1
DEFAULT_GRID_SHAPE: GridShape = (4, 4)
DEFAULT_GRID_SHAPE_OPTIONS: tuple[GridShape, ...] = ((1, 2), (2, 2), (4, 4), (8, 8))


def is_valid_grid_shape(rows: int, cols: int, *, min_lines: int = MIN_GRID_LINES) -> bool:
    return rows >= min_lines and cols >= min_lines


def format_grid_shape(rows: int, cols: int) -> str:
    return f"{rows}x{cols}"


def parse_grid_shape(text: str, *, fallback: GridShape = DEFAULT_GRID_SHAPE) -> GridShape:
    """'rows x cols' 形式の文字列を GridShape に変換する。"""
    try:
        rows_str, cols_str = text.lower().split("x", maxsplit=1)
        rows, cols = int(rows_str), int(cols_str)
    except (ValueError, IndexError):
        return fallback
    if not is_valid_grid_shape(rows, cols):
        return fallback
    return rows, cols


def normalize_grid_shape(
    rows: int, cols: int, *, fallback: GridShape = DEFAULT_GRID_SHAPE
) -> GridShape:
    if is_valid_grid_shape(rows, cols):
        return rows, cols
    return fallback


def ensure_option(options: Iterable[GridShape], shape: GridShape) -> tuple[GridShape, ...]:
    """選択肢リストに shape がなければ追加して返す (重複は除去)。"""
    unique_options = list(dict.fromkeys(options))
    if shape not in unique_options:
        unique_options.append(shape)
    return tuple(unique_options)
