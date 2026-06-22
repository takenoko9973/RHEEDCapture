from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

if TYPE_CHECKING:
    from collections.abc import Sequence

ChipValue = float | int


class ChipSelector(QWidget):
    """クリックで個別選択できる数値チップ群。"""

    selection_changed = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self._buttons: dict[ChipValue, QToolButton] = {}
        self._values: list[ChipValue] = []
        self._selected_values: list[ChipValue] = []
        self._updating = False
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._layout.addStretch(1)

    def set_values(
        self,
        values: Sequence[ChipValue],
        selected_values: Sequence[ChipValue],
    ) -> None:
        self._clear_buttons()
        self._values = list(values)
        value_set = set(self._values)
        self._selected_values = [value for value in selected_values if value in value_set]

        self._updating = True
        for value in self._values:
            text = self._format_value(value)
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setChecked(value in self._selected_values)
            button.setToolTip(text)
            button.toggled.connect(
                lambda checked, value=value: self._on_toggled(value, checked)
            )
            self._buttons[value] = button
            self._layout.insertWidget(self._layout.count() - 1, button)
        self._updating = False

    def selected_values(self) -> list[ChipValue]:
        return list(self._selected_values)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        for button in self._buttons.values():
            button.setEnabled(enabled)

    def _on_toggled(self, value: ChipValue, checked: bool) -> None:
        if self._updating:
            return

        if checked and value not in self._selected_values:
            self._selected_values.append(value)
        elif not checked:
            self._selected_values = [
                selected_value
                for selected_value in self._selected_values
                if selected_value != value
            ]

        order = {value: index for index, value in enumerate(self._values)}
        self._selected_values.sort(key=lambda selected_value: order[selected_value])
        self.selection_changed.emit(self.selected_values())

    def _clear_buttons(self) -> None:
        for button in self._buttons.values():
            self._layout.removeWidget(button)
            button.deleteLater()
        self._buttons.clear()

    @staticmethod
    def _format_value(value: ChipValue) -> str:
        return f"{value:g}"
