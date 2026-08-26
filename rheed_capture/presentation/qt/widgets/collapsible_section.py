from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """見出しボタンで任意の設定Widgetを表示・非表示にするsection。"""

    def __init__(
        self,
        title: str,
        content_widget: QWidget,
        *,
        expanded: bool = True,
    ) -> None:
        """見出し、内容Widget、初期開閉状態からsectionを構築する。"""
        super().__init__()
        self.content_widget = content_widget
        self.toggle_button = QToolButton()
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setAutoRaise(True)
        self.toggle_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.toggle_button.setToolTip(f"{title}設定の表示・非表示を切り替えます。")
        self.toggle_button.toggled.connect(self._on_toggled)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.content_widget)

        self.set_expanded(expanded)

    def is_expanded(self) -> bool:
        """sectionが開いているかを返す。"""
        return self.toggle_button.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        """sectionの開閉状態を変更する。"""
        if self.toggle_button.isChecked() != expanded:
            self.toggle_button.setChecked(expanded)
            return
        self._apply_expanded_state(expanded)

    @Slot(bool)
    def _on_toggled(self, expanded: bool) -> None:
        """見出しボタンの状態を内容Widgetと矢印へ反映する。"""
        self._apply_expanded_state(expanded)

    def _apply_expanded_state(self, expanded: bool) -> None:
        """開閉状態に応じて内容Widgetと見出し矢印を更新する。"""
        self.content_widget.setVisible(expanded)
        self.toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
