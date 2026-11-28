"""Moba Quick Connect: keyboard-first single and spreadsheet connection entry."""
from __future__ import annotations

import argparse
import copy
import csv
import os
from pathlib import Path
import re
import sys

from PySide6.QtCore import Qt, QTimer, QSize, QRect, QPoint, QEvent, QObject, QThread, Signal, Slot, QPersistentModelIndex
from PySide6.QtGui import QColor, QCursor, QFont, QFontDatabase, QIcon, QKeySequence, QPainter, QPalette, QPen, QPixmap, QPolygon, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QStyledItemDelegate,
    QStyle, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTableWidgetSelectionRange, QVBoxLayout, QWidget)

import core
import fill as spreadsheet_fill
import integration
import portable
from windows import ScopedHotkey, discover_moba, reveal_window
from key_picker import KeyLibrary, KeyPicker, FavoriteKeysDialog


STYLE = """
* {font-family:'Segoe UI','Malgun Gothic';font-size:13px;color:#eeecf7;}
QMainWindow,QDialog {background:#1c1b29;}
QWidget#page {background:#1c1b29;}
QWidget#sidebar {background:#191824;border-right:1px solid #343143;}
QFrame#card {background:#232132;border:1px solid #363345;border-radius:10px;}
QLabel {background:transparent;}
QLabel#title {font-size:18px;font-weight:650;}
QLabel#brand {font-size:16px;font-weight:650;}
QLabel#muted {color:#a7a2bd;font-size:12px;}
QLabel#eyebrow {color:#b296ff;font-size:11px;font-weight:600;}
QLabel#status {color:#b6b0ca;font-size:12px;padding:5px 0;}
QLineEdit,QComboBox {background:#171621;border:1px solid #3b374e;border-radius:9px;
padding:5px 9px;selection-background-color:#7251c9;min-height:19px;}
QLineEdit:focus,QComboBox:focus {border:1px solid #aa7aff;background:#1c192b;}
QLineEdit:disabled {color:#696477;background:#1d1b28;}
QComboBox::drop-down {border:none;width:26px;}
QComboBox QAbstractItemView {background:#262235;selection-background-color:#493667;border:1px solid #494059;}
QPushButton {background:#2b263f;border:1px solid #403650;border-radius:7px;padding:6px 11px;}
QPushButton:hover {background:#382f4e;border-color:#7b5da7;}
QPushButton:pressed {background:#49375f;}
QPushButton:disabled {color:#706a82;background:#24202f;border-color:#302a3c;}
QPushButton#primary {background:#a475fb;color:#171024;border:none;font-weight:650;min-height:20px;}
QPushButton#primary:hover {background:#b28bff;}
QPushButton#tab {background:transparent;color:#a8a1ba;border:none;border-radius:6px;padding:6px 12px;}
QPushButton#tab:checked {background:#39304f;color:#c9adff;}
QPushButton#quiet {background:transparent;border:none;color:#b6a8d4;padding:6px 9px;}
QPushButton#quiet:hover {background:#2e273f;}
QListWidget {background:transparent;border:none;outline:none;}
QListWidget::item {padding:12px;border-radius:9px;margin:2px 0;color:#beb6d3;}
QListWidget::item:selected {background:#302641;color:#d0b3ff;}
QListWidget::item:hover {background:#282235;}
QCheckBox {spacing:9px;background:transparent;}
QCheckBox::indicator {width:17px;height:17px;border:1px solid #655779;border-radius:5px;background:#171621;}
QCheckBox::indicator:checked {background:#a475fb;border-color:#a475fb;image:none;}
QTableWidget {background:#1d1b29;alternate-background-color:#23202f;gridline-color:#373142;
border:1px solid #3d344d;border-radius:11px;selection-background-color:#483263;selection-color:#faf4ff;outline:none;}
QTableWidget::item {padding:4px;border:0;}
QTableWidget::item:selected {background:#493367;}
QTableWidget QLineEdit {border:1px solid #b68aff;border-radius:2px;padding:2px;}
QHeaderView::section {background:#2a2439;color:#bfb1d4;border:0;border-right:1px solid #3b314a;
border-bottom:1px solid #42354f;padding:6px;}
QTableCornerButton::section {background:#2a2439;border:0;}
QScrollArea {border:none;background:transparent;}
QScrollBar:vertical {background:transparent;width:9px;margin:2px;}
QScrollBar:horizontal {background:#1d1b29;height:10px;margin:2px;}
QScrollBar::handle {background:#50435f;border-radius:4px;min-height:24px;min-width:24px;}
QScrollBar::add-line,QScrollBar::sub-line {height:0;width:0;}
QMenu {background:#262132;border:1px solid #4b3d5b;border-radius:8px;padding:6px;}
QMenu::item {padding:8px 24px;}
QMenu::item:selected {background:#44305e;}
QToolTip {background:#30263e;color:#e9dcff;border:1px solid #61477d;padding:6px;}
"""


def configure_application(app):
    if app.platformName() == "offscreen" and os.name == "nt":
        # Qt's offscreen Windows plugin does not enumerate system fonts.
        for name in ("segoeui.ttf", "segoeuib.ttf", "malgun.ttf", "malgunbd.ttf"):
            path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
    app.setStyle("Fusion")
    palette = QPalette()
    for role, value in ((QPalette.ColorRole.Window, "#232132"), (QPalette.ColorRole.WindowText, "#eeecf7"),
                        (QPalette.ColorRole.Base, "#1d1b29"), (QPalette.ColorRole.AlternateBase, "#23202f"),
                        (QPalette.ColorRole.Text, "#eeecf7"), (QPalette.ColorRole.Button, "#2b263f"),
                        (QPalette.ColorRole.ButtonText, "#eeecf7"), (QPalette.ColorRole.Highlight, "#493367"),
                        (QPalette.ColorRole.HighlightedText, "#faf4ff")):
        palette.setColor(role, QColor(value))
    app.setPalette(palette)
    app.setFont(QFont("Malgun Gothic", 10))
    app.setStyleSheet(STYLE)


def icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#a475fb"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(1, 1, 62, 62, 18, 18)
    painter.setPen(QPen(QColor("#1c112e"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(18, 22, 29, 32)
    painter.drawLine(29, 32, 18, 42)
    painter.drawLine(35, 42, 47, 42)
    painter.end()
    return QIcon(pixmap)


def label(text, name=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback=None, name=None):
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    if callback:
        widget.clicked.connect(callback)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


def line(placeholder=""):
    widget = QLineEdit()
    widget.setPlaceholderText(placeholder)
    widget.setClearButtonEnabled(True)
    return widget


def card():
    widget = QFrame()
    widget.setObjectName("card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(8)
    return widget, layout


class ConnectionForm(QWidget):
    def __init__(self, parent=None, *, address_widgets=None, key_library=None):
        super().__init__(parent)
        self.kind = "SSH"
        self.fields = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        outer.setAlignment(Qt.AlignmentFlag.AlignTop)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        entries = [("name", "연결 이름", "비워두면 IP로 자동 생성"), ("folder", "저장 폴더", "Quick Connect")]
        if address_widgets:
            entries += [("host", "접속 IP", ""), ("protocol", "방식", "")]
        entries += [("user", "사용자", "opc"), ("port", "포트", "22")]
        for index, (key, title, hint) in enumerate(entries):
            row, col = divmod(index, 2)
            grid.addWidget(label(title, "muted"), row * 2, col)
            widget = address_widgets[("host", "protocol").index(key)] if key in ("host", "protocol") else line(hint)
            widget.setAccessibleName(title)
            if key in ("name", "host"):
                widget.editingFinished.connect(lambda widget=widget: widget.setText(widget.text().strip()))
            if key not in ("host", "protocol"):
                self.fields[key] = widget
            grid.addWidget(widget, row * 2 + 1, col)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        outer.addLayout(grid)
        self.key_widget = QWidget()
        key_layout = QVBoxLayout(self.key_widget)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(4)
        key_layout.addWidget(label("SSH 키", "muted"))
        self.fields["key_path"] = KeyPicker(key_library, self)
        self.fields["key_path"].setAccessibleName("SSH 키 경로")
        key_layout.addWidget(self.fields["key_path"])
        outer.addWidget(self.key_widget)
        self.jump = QCheckBox("Bastion 사용")
        self.jump.setAccessibleName("Bastion 사용")
        jump_header = QHBoxLayout()
        jump_header.addWidget(self.jump)
        jump_header.addStretch(1)
        self.jump_expand = button("Bastion 펼치기", name="quiet")
        self.jump_expand.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
        self.jump_expand.setCheckable(True)
        jump_header.addWidget(self.jump_expand)
        outer.addLayout(jump_header)
        self.jump_panel = QFrame()
        jump_grid = QGridLayout(self.jump_panel)
        jump_grid.setContentsMargins(0, 4, 0, 0)
        jump_grid.setHorizontalSpacing(10)
        jump_grid.setVerticalSpacing(4)
        for index, (key, title, hint) in enumerate((
            ("bastion_host", "Bastion 호스트", "IP 또는 호스트"),
            ("bastion_port", "Bastion 포트", "22"),
            ("bastion_user", "Bastion 사용자", "opc"),
            ("bastion_key_path", "Bastion 키", "키 파일 경로"))):
            r, c = divmod(index, 2)
            jump_grid.addWidget(label(title, "muted"), r * 2, c)
            self.fields[key] = KeyPicker(key_library, self) if key == "bastion_key_path" else line(hint)
            self.fields[key].setAccessibleName(title)
            if key == "bastion_key_path":
                jump_grid.addWidget(self.fields[key], r * 2 + 1, c)
            else:
                jump_grid.addWidget(self.fields[key], r * 2 + 1, c)
        outer.addWidget(self.jump_panel)
        self.fields["bastion_host"].editingFinished.connect(lambda: self.fields["bastion_host"].setText(self.fields["bastion_host"].text().strip()))
        self.jump_expand.toggled.connect(self.jump_panel.setVisible)
        self.jump_expand.toggled.connect(lambda expanded: self.jump_expand.setText("Bastion 접기" if expanded else "Bastion 펼치기"))
        self.jump_expand.toggled.connect(lambda expanded: self.jump_expand.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown if expanded else QStyle.StandardPixmap.SP_ArrowRight)))
        self.jump.toggled.connect(self.jump_expand.setChecked)
        self.jump_panel.hide()

    def pick_key(self, key):
        self.fields[key].browse()

    def set_row(self, row):
        self.kind = row.get("protocol", "SSH")
        for key, widget in self.fields.items():
            widget.setText(str(row.get(key, "")))
        self.key_widget.setVisible(self.kind == "SSH")
        self.jump.blockSignals(True)
        self.jump.setChecked(bool(row.get("bastion_host")))
        self.jump.blockSignals(False)
        self.jump_expand.setChecked(False)

    def get_row(self):
        result = {key: widget.text().strip() for key, widget in self.fields.items()}
        result["protocol"] = self.kind
        if not self.jump.isChecked():
            result["bastion_host"] = ""
        return result


class ProtocolDelegate(QStyledItemDelegate):
    def eventFilter(self, editor, event):
        if isinstance(editor, KeyPicker):
            return False  # Composite editor owns its child focus/completion events.
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
            table = self.parent()
            row, col = table.currentRow(), table.currentColumn()
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
            QTimer.singleShot(0, lambda: table.move_down(row, col))
            return True
        return super().eventFilter(editor, event)

    def createEditor(self, parent, option, index):
        if index.column() == 5:
            editor = KeyPicker(self.parent().key_library, parent, table_editor=True)
            persistent = QPersistentModelIndex(index)
            editor.advance.connect(lambda: self.finish_key(editor, persistent, True))
            editor.finished.connect(lambda: self.finish_key(editor, persistent, False))
            return editor
        if index.row() % 2 == 0 and self.parent().field_at(index.row(), index.column()) == "protocol":
            editor = QComboBox(parent)
            editor.addItems(["SSH", "RDP"])
            return editor
        return super().createEditor(parent, option, index)

    def finish_key(self, editor, index, advance=False):
        if editor.closed or not index.isValid():
            return
        editor.closed = True
        row, col = index.row(), index.column()
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
        if advance:
            QTimer.singleShot(0, lambda: self.parent().move_down(row, col))

    def paint(self, painter, option, index):
        if not index.row() % 2 and index.column() == 0:
            painter.save()
            selected = bool(option.state & QApplication.style().StateFlag.State_Selected)
            painter.fillRect(option.rect, QColor("#493367" if selected else "#1d1b29"))
            painter.setPen(QColor("#eeecf7"))
            rect = option.rect.adjusted(5, 0, -25, 0)
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             option.fontMetrics.elidedText(index.data() or "", Qt.TextElideMode.ElideRight, max(0, rect.width())))
            expanded = index.row() // 2 in self.parent().expanded_rows
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#b68aff"))
            x, y = option.rect.right() - 12, option.rect.center().y()
            points = [(x - 4, y - 2), (x + 4, y - 2), (x, y + 3)] if expanded else [(x - 2, y - 4), (x - 2, y + 4), (x + 3, y)]
            painter.drawPolygon(QPolygon([QPoint(*point) for point in points]))
            painter.restore()
            return
        if index.column() == 5:
            selected = bool(option.state & QApplication.style().StateFlag.State_Selected) and index.row() % 2 == self.parent().currentRow() % 2
            painter.save()
            painter.fillRect(option.rect, QColor("#493367" if selected else "#2b233a" if index.row() % 2 else "#1d1b29"))
            painter.setFont(option.font)
            painter.setPen(QColor("#cfb9ec" if index.data() else "#8f7da9"))
            text = index.data() or ("Bastion 키" if index.row() % 2 else "키 선택")
            rect = option.rect.adjusted(5, 0, -26, 0)
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             option.fontMetrics.elidedText(text, Qt.TextElideMode.ElideMiddle, max(0, rect.width())))
            self.parent().style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon).paint(
                painter, QRect(option.rect.right() - 21, option.rect.center().y() - 8, 16, 16))
            painter.restore()
            return
        if index.row() % 2:
            text = index.data() or {1: "Bastion IP", 3: "사용자", 4: "22", 5: "Bastion 키"}.get(index.column(), "")
            selected = bool(option.state & QApplication.style().StateFlag.State_Selected) and self.parent().currentRow() % 2 == 1
            painter.save()
            painter.fillRect(option.rect, QColor("#493367" if selected else "#2b233a"))
            painter.setFont(option.font)
            painter.setPen(QColor("#cfb9ec" if index.data() else "#8f7da9"))
            rect = option.rect.adjusted(5, 0, -5, 0)
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             option.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, max(0, rect.width())))
            painter.restore()
            return
        if self.parent().currentRow() % 2 == 1:
            option.state &= ~QApplication.style().StateFlag.State_Selected
        super().paint(painter, option, index)

    def editorEvent(self, event, model, option, index):
        if not index.row() % 2 and index.column() == 0 and event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton and event.position().x() >= option.rect.right() - 25:
            self.parent().toggle_bastion(index.row() // 2)
            return True
        if index.column() == 5 and event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton and event.position().x() >= option.rect.right() - 25:
            table = self.parent()
            table.commit_editor()
            table.setCurrentIndex(index)
            table.edit(index)
            QTimer.singleShot(0, lambda: self.browse_current_key(index))
            return True
        return super().editorEvent(event, model, option, index)

    def browse_current_key(self, index):
        table = self.parent()
        if table.currentIndex() == index:
            for editor in table.viewport().findChildren(KeyPicker):
                if editor.isVisible() and not editor.closed:
                    editor.browse()
                    break

    def setEditorData(self, editor, index):
        if isinstance(editor, KeyPicker):
            editor.setText(index.data() or "")
        elif isinstance(editor, QComboBox):
            editor.setCurrentText(index.data() or "SSH")
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, KeyPicker):
            model.setData(index, editor.text())
        elif isinstance(editor, QComboBox):
            model.setData(index, editor.currentText())
        else:
            super().setModelData(editor, model, index)


class ConnectionRowHeader(QHeaderView):
    def __init__(self, table):
        super().__init__(Qt.Orientation.Vertical, table)
        self.table = table
        self.anchor = None
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        image = QPixmap(24, 24)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setPen(QPen(QColor("#eee7ff"), 1))
        painter.setBrush(QColor("#282033"))
        painter.drawPolygon(QPolygon([QPoint(3, 8), QPoint(13, 8), QPoint(13, 3), QPoint(22, 12), QPoint(13, 21), QPoint(13, 16), QPoint(3, 16)]))
        painter.end()
        self.viewport().setCursor(QCursor(image, 21, 12))
        self.setToolTip("클릭/드래그: 연결 전체 선택\nCtrl+C: 숨긴 Bastion까지 복사")

    def mousePressEvent(self, event):
        section = self.logicalIndexAt(event.position().toPoint())
        if section >= 0 and event.button() == Qt.MouseButton.LeftButton:
            self.anchor = section // 2
            self.table.select_connection_rows(self.anchor, self.anchor, event.modifiers())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        section = self.logicalIndexAt(event.position().toPoint())
        if self.anchor is not None and section >= 0 and event.buttons() & Qt.MouseButton.LeftButton:
            self.table.select_connection_rows(self.anchor, section // 2)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.anchor = None
        super().mouseReleaseEvent(event)


class ConnectionGrid(QTableWidget):
    bastionVisibilityChanged = Signal(bool)
    MAIN_FIELDS = ("name", "host", "protocol", *core.FIELDS[3:7])
    JUMP_FIELDS = (None, "bastion_host", None, "bastion_user", "bastion_port", "bastion_key_path", None)
    FULL_FIELDS = (*MAIN_FIELDS, *core.FIELDS[7:])

    def __init__(self, profile, protocol=lambda: "SSH", parent=None, *, key_library=None):
        super().__init__(0, len(self.MAIN_FIELDS), parent)
        self.profile = profile
        self.key_library = key_library
        self.protocol = protocol
        self.history = []
        self.mutating = False
        self.drag_seed = None
        self.drag_target = None
        self.drag_before = None
        self.drag_series = False
        self.drag_position = None
        self.bastion_visible = False
        self.expanded_rows = set()
        self.whole_rows = set()
        self.drag_layer = 0
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setInterval(90)
        self.scroll_timer.timeout.connect(self.drag_autoscroll)
        self.setHorizontalHeaderLabels([dict(zip(core.FIELDS, core.HEADERS))[f] for f in self.MAIN_FIELDS])
        self.setAlternatingRowColors(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed |
                             QAbstractItemView.EditTrigger.AnyKeyPressed | QAbstractItemView.EditTrigger.SelectedClicked)
        self.setItemDelegate(ProtocolDelegate(self))
        for index, width in enumerate((160, 140, 58, 95, 52, 170, 130)):
            self.setColumnWidth(index, width)
        self.setVerticalHeader(ConnectionRowHeader(self))
        self.verticalHeader().setDefaultSectionSize(30)
        self.verticalHeader().setMinimumSectionSize(26)
        self.verticalHeader().setFixedWidth(32)
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.itemChanged.connect(self.on_item_changed)
        self.cellPressed.connect(lambda *_: self.whole_rows.clear())
        self.append_rows(8, record=False)
        self.previous = self.rows()
        for keys, handler in (("Ctrl+V", self.paste), ("Ctrl+C", self.copy), ("Ctrl+D", self.fill_down),
                              ("Ctrl+Z", self.undo), ("Delete", self.clear_cells)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_menu)
        self.set_details(False)

    def set_details(self, enabled):
        for col in (5, 6):
            self.setColumnHidden(col, not enabled)

    def set_bastion(self, enabled):
        self.commit_editor()
        self.bastion_visible = enabled
        self.expanded_rows = set(range(self.logical_count())) if enabled else set()
        for row in range(1, self.rowCount(), 2):
            self.setRowHidden(row, not enabled)
        if not enabled and self.currentRow() % 2:
            self.setCurrentCell(self.currentRow() - 1, max(0, self.currentColumn()))
        self.bastionVisibilityChanged.emit(bool(enabled))
        self.viewport().update()

    def toggle_bastion(self, row):
        self.commit_editor()
        if row in self.expanded_rows:
            self.expanded_rows.remove(row)
        else:
            self.expanded_rows.add(row)
        self.setRowHidden(row * 2 + 1, row not in self.expanded_rows)
        self.bastion_visible = len(self.expanded_rows) == self.logical_count()
        self.bastionVisibilityChanged.emit(self.bastion_visible)
        self.viewport().update()

    def select_connection_rows(self, first, last, modifiers=Qt.KeyboardModifier.NoModifier):
        self.commit_editor()
        picked = set(range(min(first, last), max(first, last) + 1))
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            picked ^= self.whole_rows
        self.setCurrentCell(last * 2, 0)
        self.clearSelection()
        for row in sorted(picked):
            self.setRangeSelected(QTableWidgetSelectionRange(row * 2, 0, row * 2 + 1, self.columnCount() - 1), True)
        self.whole_rows = picked
        self.setFocus()

    def field_at(self, row, column):
        return (self.JUMP_FIELDS if row % 2 else self.MAIN_FIELDS)[column]

    def logical_count(self):
        return self.rowCount() // 2

    def rows(self):
        result = []
        for row in range(0, self.rowCount(), 2):
            record = {}
            for physical, fields in ((row, self.MAIN_FIELDS), (row + 1, self.JUMP_FIELDS)):
                for col, field in enumerate(fields):
                    if field:
                        item = self.item(physical, col)
                        record[field] = item.text() if item else ""
            result.append(record)
        return result

    def remember(self):
        self.history.append(copy.deepcopy(self.previous))
        self.history = self.history[-50:]

    def set_rows(self, rows):
        if self.bastion_visible:
            self.expanded_rows = set(range(len(rows)))
        self.expanded_rows.intersection_update(range(len(rows)))
        self.whole_rows.clear()
        self.mutating = True
        self.setRowCount(len(rows) * 2)
        for r, row in enumerate(rows):
            for layer, fields in enumerate((self.MAIN_FIELDS, self.JUMP_FIELDS)):
                physical = r * 2 + layer
                self.setVerticalHeaderItem(physical, QTableWidgetItem("" if layer else str(r + 1)))
                self.setRowHeight(physical, 28 if layer else 32)
                for c, field in enumerate(fields):
                    value = str(row.get(field, ""))
                    if field in ("name", "host", "bastion_host"):
                        value = value.strip()
                    item = QTableWidgetItem(value if field else ("Bastion" if c == 0 else ""))
                    if layer:
                        item.setBackground(QColor("#2b233a"))
                        item.setForeground(QColor("#cfb9ec") if field else QColor("#9780b6"))
                    if not field:
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    self.setItem(physical, c, item)
                self.setRowHidden(physical, bool(layer and r not in self.expanded_rows))
        self.mutating = False
        self.previous = self.rows()
        self.bastionVisibilityChanged.emit(bool(rows) and len(self.expanded_rows) == len(rows))

    def append_rows(self, count=1, *, record=True):
        if self.logical_count() + count > 2000:
            raise ValueError("일괄 입력은 최대 2,000행까지 가능합니다.")
        if record and hasattr(self, "previous"):
            self.remember()
        rows = self.rows() + [core.new_row(self.profile(), self.protocol()) for _ in range(count)]
        self.set_rows(rows)

    def on_item_changed(self, item):
        if self.mutating:
            return
        self.remember()
        if self.field_at(item.row(), item.column()) in ("name", "host", "bastion_host"):
            self.mutating = True
            item.setText(item.text().strip())
            self.mutating = False
        if item.row() % 2 == 0 and self.field_at(item.row(), item.column()) == "protocol" and item.text().upper() in core.DEFAULTS:
            rows = self.rows()
            old = rows[item.row() // 2]
            fresh = core.new_row(self.profile(), item.text().upper())
            for f in ("host", "name", "folder"):
                fresh[f] = old[f]
            rows[item.row() // 2] = fresh
            self.set_rows(rows)
        self.previous = self.rows()

    def paste_text(self, text):
        matrix = core.parse_clipboard(text)
        if not matrix:
            return
        physical, c0 = max(0, self.currentRow()), max(0, self.currentColumn())
        r0, layer = divmod(physical, 2)
        fields = self.JUMP_FIELDS if layer else self.MAIN_FIELDS
        if not layer and c0 == 0 and all(len(r) == 1 and re.fullmatch(r'[0-9a-fA-F:.]+', r[0].strip()) for r in matrix):
            c0 = 1
        if not layer and c0 == 0 and all(len(r) == len(self.FULL_FIELDS) for r in matrix):
            fields = self.FULL_FIELDS
        if r0 + len(matrix) > 2000 or c0 + max(map(len, matrix), default=0) > len(fields):
            raise ValueError("붙여넣을 범위가 표의 최대 크기를 넘습니다.")
        self.remember()
        rows = self.rows()
        while len(rows) < r0 + len(matrix):
            rows.append(core.new_row(self.profile(), self.protocol()))
        for dy, values in enumerate(matrix):
            for dx, value in enumerate(values):
                field = fields[c0 + dx]
                if field:
                    rows[r0 + dy][field] = value.strip()
            if not layer and c0 <= 2 < c0 + len(values):
                kind = rows[r0 + dy]["protocol"].upper()
                if kind in core.DEFAULTS:
                    old = self.previous[r0 + dy] if r0 + dy < len(self.previous) else core.new_row(self.profile(), self.protocol())
                    for field in ("user", "port", "key_path", "bastion_host", "bastion_user", "bastion_port", "bastion_key_path"):
                        pasted_fields = set(fields[c0:c0 + len(values)])
                        if field not in pasted_fields and rows[r0 + dy][field] == old[field]:
                            rows[r0 + dy][field] = self.profile()[kind][field]
                    rows[r0 + dy]["protocol"] = kind
        self.set_rows(rows)
        self.setCurrentCell(physical, c0)

    def paste(self):
        try:
            self.paste_text(QApplication.clipboard().text())
        except ValueError as exc:
            QMessageBox.warning(self, "붙여넣기", str(exc))

    def copy(self):
        self.commit_editor()
        if self.whole_rows:
            import io
            output = io.StringIO()
            writer = csv.writer(output, delimiter="\t", lineterminator="\r\n")
            rows = self.rows()
            writer.writerows([[rows[r].get(f, "") for f in self.FULL_FIELDS] for r in sorted(self.whole_rows)])
            QApplication.clipboard().setText(output.getvalue().rstrip("\r\n"))
            return
        selected = self.selectedRanges()
        if not selected:
            return
        area = self.selection_rectangle()
        layer = max(0, self.currentRow()) % 2
        fields = self.JUMP_FIELDS if layer else self.MAIN_FIELDS
        rows = self.rows()
        text = "\r\n".join("\t".join(rows[r].get(fields[c], "") for c in range(area[1], area[3] + 1))
                           for r in range(area[0], area[2] + 1))
        QApplication.clipboard().setText(text)

    def fill_down(self):
        selected = self.selectedRanges()
        if not selected:
            return
        area = self.selection_rectangle()
        fields = self.JUMP_FIELDS if max(0, self.currentRow()) % 2 else self.MAIN_FIELDS
        rows = self.rows()
        if area[0] == area[2]:
            self.duplicate_rows()
            return
        self.remember()
        for r in range(area[0] + 1, area[2] + 1):
            for c in range(area[1], area[3] + 1):
                if fields[c]:
                    rows[r][fields[c]] = rows[area[0]][fields[c]]
        self.set_rows(rows)

    def duplicate_rows(self):
        chosen = sorted({i.row() // 2 for i in self.selectedIndexes()}) or [max(0, self.currentRow()) // 2]
        rows = self.rows()
        if len(rows) + len(chosen) > 2000:
            raise ValueError("일괄 입력은 최대 2,000행까지 가능합니다.")
        self.remember()
        for r in reversed(chosen):
            new = copy.deepcopy(rows[r])
            new["name"] = ""
            rows.insert(r + 1, new)
        expanded = set()
        for r in self.expanded_rows:
            moved = r + sum(i < r for i in chosen)
            expanded.add(moved)
            if r in chosen:
                expanded.add(moved + 1)
        self.expanded_rows = expanded
        self.set_rows(rows)
        self.setCurrentCell((chosen[0] + 1) * 2, 0)

    def delete_rows(self):
        chosen = {i.row() // 2 for i in self.selectedIndexes()}
        self.remember()
        self.expanded_rows = {r - sum(i < r for i in chosen) for r in self.expanded_rows if r not in chosen}
        self.set_rows([row for r, row in enumerate(self.rows()) if r not in chosen] or [core.new_row(self.profile(), self.protocol())])

    def commit_editor(self):
        editor = QApplication.focusWidget()
        candidate = editor
        while candidate is not None and candidate != self:
            if isinstance(candidate, KeyPicker):
                delegate = self.itemDelegateForIndex(self.currentIndex())
                delegate.finish_key(candidate, self.currentIndex())
                return
            candidate = candidate.parentWidget()
        if self.state() == QAbstractItemView.State.EditingState and isinstance(editor, (QLineEdit, QComboBox)):
            delegate = self.itemDelegateForIndex(self.currentIndex())
            delegate.commitData.emit(editor)
            delegate.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)

    def move_down(self, row=None, column=None):
        self.whole_rows.clear()
        row = self.currentRow() if row is None else row
        column = self.currentColumn() if column is None else column
        if row < 0:
            row, column = -1, 0
        next_row = row + 2 if row >= 0 else 0
        if next_row // 2 >= 2000:
            return
        if next_row >= self.rowCount():
            self.append_rows()
        self.setCurrentCell(next_row, max(0, column))
        self.scrollToItem(self.item(next_row, max(0, column)))
        self.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.drag_seed:
            self.cancel_fill()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
            self.commit_editor()
            self.move_down()
            event.accept()
            return
        super().keyPressEvent(event)

    def selection_rectangle(self):
        ranges = self.selectedRanges()
        if not ranges:
            return None
        area = next((r for r in ranges if r.topRow() <= self.currentRow() <= r.bottomRow()
                     and r.leftColumn() <= self.currentColumn() <= r.rightColumn()), ranges[-1])
        return (area.topRow() // 2, area.leftColumn(), area.bottomRow() // 2, area.rightColumn())

    def rectangle_pixels(self, rectangle):
        if rectangle is None:
            return QRect()
        top, left, bottom, right = rectangle
        visible = [c for c in range(left, right + 1) if not self.isColumnHidden(c)]
        if not visible or bottom >= self.logical_count():
            return QRect()
        layer = self.drag_layer if self.drag_seed else max(0, self.currentRow()) % 2
        first = self.visualRect(self.model().index(top * 2 + layer, visible[0]))
        last = self.visualRect(self.model().index(bottom * 2 + layer, visible[-1]))
        return first.united(last)

    def fill_handle(self):
        rect = self.rectangle_pixels(self.selection_rectangle())
        if rect.isEmpty():
            return QRect()
        return QRect(rect.right() - 5, rect.bottom() - 5, 9, 9)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        if self.drag_target:
            area = self.rectangle_pixels(self.drag_target)
            painter.setPen(QPen(QColor("#ba91ff"), 2))
            painter.setBrush(QColor(164, 117, 251, 24))
            painter.drawRect(area.adjusted(0, 0, -1, -1))
        handle = self.fill_handle()
        if not handle.isEmpty():
            painter.setBrush(QColor("#b68aff"))
            painter.setPen(QPen(QColor("#171220"), 1))
            painter.drawRect(handle)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.fill_handle().adjusted(-3, -3, 3, 3).contains(event.position().toPoint()):
            self.commit_editor()
            self.drag_seed = self.selection_rectangle()
            self.drag_layer = max(0, self.currentRow()) % 2
            self.drag_target = self.drag_seed
            self.drag_before = copy.deepcopy(self.rows())
            self.drag_series = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self.drag_position = event.position().toPoint()
            self.scroll_timer.start()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_seed:
            self.drag_position = event.position().toPoint()
            self.drag_series = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self.preview_fill(self.drag_position)
            event.accept()
            return
        if self.fill_handle().adjusted(-3, -3, 3, 3).contains(event.position().toPoint()):
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            self.viewport().setToolTip("드래그: 복사   Ctrl+드래그: 번호 +1")
        else:
            self.viewport().unsetCursor()
            self.viewport().setToolTip("")
        super().mouseMoveEvent(event)

    def preview_fill(self, point):
        top, left, bottom, right = self.drag_seed
        y = max(0, min(point.y(), self.viewport().height() - 1))
        x = max(0, min(point.x(), self.viewport().width() - 1))
        physical = self.rowAt(y)
        row = physical // 2
        if physical < 0:
            last = self.rowCount() - 1
            row = self.logical_count() + max(0, (y - self.rowViewportPosition(last) - self.rowHeight(last)) // 60)
        row = min(1999, row)
        col = self.columnAt(x)
        if col < 0:
            col = max(c for c in range(self.columnCount()) if not self.isColumnHidden(c))
        vertical = max(top - row, row - bottom, 0)
        horizontal = max(left - col, col - right, 0)
        if vertical >= horizontal:
            target = (min(top, row), left, max(bottom, row), right)
        else:
            target = (top, min(left, col), bottom, max(right, col))
        if target[2] >= self.logical_count():
            self.append_rows(target[2] - self.logical_count() + 1, record=False)
        self.drag_target = target
        self.viewport().update()

    def drag_autoscroll(self):
        if not self.drag_seed or self.drag_position is None:
            self.scroll_timer.stop()
            return
        point = self.drag_position
        bar = self.verticalScrollBar()
        if point.y() > self.viewport().height() - 20:
            if bar.value() == bar.maximum() and self.logical_count() < 2000:
                self.append_rows(min(4, 2000 - self.logical_count()), record=False)
            bar.setValue(bar.value() + max(1, bar.singleStep()))
        elif point.y() < 20:
            bar.setValue(bar.value() - max(1, bar.singleStep()))
        hbar = self.horizontalScrollBar()
        if point.x() > self.viewport().width() - 20:
            hbar.setValue(hbar.value() + max(1, hbar.singleStep()))
        elif point.x() < 20:
            hbar.setValue(hbar.value() - max(1, hbar.singleStep()))
        self.preview_fill(point)

    def apply_fill(self, seed, target, *, series=False, before=None):
        before = copy.deepcopy(self.rows()) if before is None else before
        rows = self.rows()
        for r in range(seed[0], seed[2] + 1):
            rows[r] = copy.deepcopy(before[r])
        layer = self.drag_layer
        fields = self.JUMP_FIELDS if layer else self.MAIN_FIELDS
        # Reserved cells in the Bastion row are display-only. Fill a temporary
        # matrix and copy back editable fields, preserving the connection above.
        whole = bool(self.whole_rows and seed[1] == 0 and seed[3] == self.columnCount() - 1)
        fill_fields = self.FULL_FIELDS if whole else tuple(field or f"_reserved_{col}" for col, field in enumerate(fields))
        matrix = [{**row, **{field: "" for field in fill_fields if field.startswith("_reserved_")}} for row in rows]
        fill_seed = (seed[0], 0, seed[2], len(fill_fields) - 1) if whole else seed
        fill_target = (target[0], 0, target[2], len(fill_fields) - 1) if whole else target
        result = spreadsheet_fill.fill(matrix, fill_fields, fill_seed, fill_target, series=series)
        result = [{field: row[field] for field in core.FIELDS} for row in result]
        self.history.append(copy.deepcopy(before))
        self.history = self.history[-50:]
        self.set_rows(result)
        self.setCurrentCell(target[0] * 2 + layer, target[1])
        self.clearSelection()
        self.setRangeSelected(QTableWidgetSelectionRange(target[0] * 2 + layer, target[1], target[2] * 2 + layer, target[3]), True)
        if whole:
            self.whole_rows = set(range(target[0], target[2] + 1))
        self.viewport().update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_seed:
            seed, target, before = self.drag_seed, self.drag_target, self.drag_before
            series = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self.scroll_timer.stop()
            self.drag_seed = self.drag_target = self.drag_before = None
            self.drag_position = None
            if target != seed:
                try:
                    self.apply_fill(seed, target, series=series, before=before)
                except ValueError as exc:
                    self.set_rows(before)
                    QMessageBox.warning(self, "채우기", str(exc))
            else:
                self.set_rows(before)
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def cancel_fill(self):
        before = self.drag_before
        self.scroll_timer.stop()
        self.drag_seed = self.drag_target = self.drag_before = None
        self.drag_position = None
        if before is not None:
            self.set_rows(before)
        self.viewport().unsetCursor()
        self.viewport().update()

    def clear_cells(self):
        self.remember()
        rows = self.rows()
        for index in self.selectedIndexes():
            field = self.field_at(index.row(), index.column())
            if field and index.row() % 2 == max(0, self.currentRow()) % 2:
                rows[index.row() // 2][field] = ""
        self.set_rows(rows)

    def undo(self):
        if self.history:
            self.set_rows(self.history.pop())

    def context_menu(self, point):
        menu = QMenu(self)
        for title, action in (("붙여넣기   Ctrl+V", self.paste), ("복사   Ctrl+C", self.copy),
                              ("아래로 채우기   Ctrl+D", self.fill_down), ("행 복제", self.duplicate_rows),
                              ("행 삭제", self.delete_rows), ("실행 취소   Ctrl+Z", self.undo)):
            menu.addAction(title, action)
        menu.exec(self.viewport().mapToGlobal(point))


class RegistrationWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, target, rows, root):
        super().__init__()
        self.target, self.rows, self.root = target, rows, root

    def run(self):
        try:
            result = integration.register(self.target, self.rows, self.root, self.progress.emit)
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, store, *, dry_run=False, no_tray=False):
        super().__init__()
        self.store, self.dry_run, self.no_tray = store, dry_run, no_tray
        self.key_library = KeyLibrary(store, self)
        self.quitting = False
        self.hotkey = None
        self.registration_thread = None
        self.setWindowTitle("Moba Quick Connect " + core.VERSION)
        self.setWindowIcon(icon())
        self.resize(860, 440)
        self.setMinimumSize(760, 420)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        right = QWidget()
        right.setObjectName("page")
        body = QVBoxLayout(right)
        body.setContentsMargins(12, 10, 12, 8)
        body.setSpacing(8)
        header = QHBoxLayout()
        tabs = QFrame()
        tabs.setStyleSheet("QFrame {background:#16151f;border:1px solid #312a40;border-radius:11px;}")
        tab_layout = QHBoxLayout(tabs)
        tab_layout.setContentsMargins(3, 3, 3, 3)
        self.tabs = []
        for i, text in enumerate(("단건 입력", "일괄 입력")):
            item = button(text, lambda _=False, index=i: self.select_page(index), "tab")
            item.setCheckable(True)
            self.tabs.append(item)
            tab_layout.addWidget(item)
        header.addWidget(tabs)
        header.addStretch(1)
        self.profiles = QComboBox()
        self.profiles.setAccessibleName("기본값 프로필")
        self.profiles.setMinimumWidth(110)
        self.profiles.setMaximumWidth(180)
        header.addWidget(self.profiles)
        header.addWidget(button("+", self.new_profile, "quiet"))
        files = button("파일", name="quiet")
        menu = QMenu(files)
        menu.addAction("연결 가져오기", self.import_package)
        menu.addAction("입력한 연결 내보내기 (키 포함)", self.export_current_package)
        menu.addAction("등록 기록 내보내기 (키 포함)", lambda: self.perform(lambda: self.export_package_rows(self.store.state["connections"])))
        menu.addAction("MobaXterm 세션 파일만 내보내기", self.export_bulk)
        files.setMenu(menu)
        header.addWidget(files)
        header.addWidget(button("즐겨찾는 키", self.manage_keys, "quiet"))
        header.addWidget(button("기본값 설정", lambda: self.select_page(2), "quiet"))
        header.addWidget(button("숨기기", self.hide, "quiet"))
        body.addLayout(header)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        self.make_single()
        self.make_bulk()
        self.make_settings()
        self.status = label("", "status")
        self.status.setWordWrap(True)
        self.status.hide()
        self.status.setToolTip("Moba Quick Connect " + core.VERSION + " · Ctrl+Shift+Space")
        body.addWidget(self.status)
        layout.addWidget(right, 1)
        self.profiles.currentTextChanged.connect(self.change_profile)
        self.refresh_profiles()
        self.select_page(0)
        if not self.store.state["moba_exe"]:
            self.store.state["moba_exe"] = discover_moba()
        self.exe_field.setText(self.store.state["moba_exe"])
        self.tray = None
        if not no_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icon(), self)
            self.tray.setToolTip("Moba Quick Connect · Ctrl+Shift+Space")
            menu = QMenu()
            menu.addAction("빠른 연결", self.show_popup)
            menu.addAction("기본값 설정", lambda: (self.show_popup(), self.select_page(2)))
            menu.addSeparator()
            menu.addAction("종료", self.quit_app)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.show_popup() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
            self.tray.show()
        for sequence, callback in (("Escape", self.escape), ("Ctrl+Return", self.primary_action),
                                    ("Ctrl+1", lambda: self.select_page(0)), ("Ctrl+2", lambda: self.select_page(1))):
            QShortcut(QKeySequence(sequence), self).activated.connect(callback)

    def make_single(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self.single_protocol = QComboBox()
        self.single_protocol.addItems(["SSH", "RDP"])
        self.single_protocol.setAccessibleName("단건 연결 방식")
        self.single_protocol.currentTextChanged.connect(lambda _: self.apply_single_defaults())
        self.host = line("")
        self.host.setObjectName("host")
        self.host.setAccessibleName("접속 IP")
        self.host.returnPressed.connect(self.connect_single)
        self.single_card, card_layout = card()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.single_form = ConnectionForm(address_widgets=(self.host, self.single_protocol), key_library=self.key_library)
        scroll.setWidget(self.single_form)
        card_layout.addWidget(scroll)
        outer.addWidget(self.single_card, 1)
        actions = QHBoxLayout()
        actions.addWidget(button("기본값으로 저장", self.save_single_defaults, "quiet"))
        actions.addStretch(1)
        self.single_action = button("세션 추가", self.connect_single, "primary")
        self.single_action.setToolTip("Enter 또는 Ctrl+Enter · 기존 MobaXterm에 추가 후 재시작")
        self.single_action.setMinimumWidth(180)
        actions.addWidget(self.single_action)
        outer.addLayout(actions)
        self.pages.addWidget(page)

    def make_bulk(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        controls = QHBoxLayout()
        controls.addWidget(button("+ 행 추가", lambda: self.grid.append_rows()))
        controls.addWidget(button("행 복제", lambda: self.grid.duplicate_rows()))
        controls.addWidget(button("행 삭제", lambda: self.grid.delete_rows()))
        controls.addStretch(1)
        self.bulk_protocol = QComboBox()
        self.bulk_protocol.addItems(["SSH", "RDP"])
        self.bulk_protocol.setAccessibleName("일괄 새 행 기본 방식")
        self.bulk_protocol.setToolTip("빈 행과 새 행에 적용할 기본 방식")
        self.bulk_protocol.currentTextChanged.connect(self.change_bulk_kind)
        controls.addWidget(self.bulk_protocol)
        self.details = QCheckBox("키 / 폴더")
        self.details.setChecked(True)
        self.details.toggled.connect(lambda checked: self.grid.set_details(checked))
        controls.addWidget(self.details)
        self.bastion_rows = button("Bastion 모두 펼치기")
        self.bastion_rows.setCheckable(True)
        self.bastion_rows.setToolTip("연결 이름 오른쪽 화살표로 개별 펼치기")
        self.bastion_rows.toggled.connect(lambda checked: self.grid.set_bastion(checked))
        controls.addWidget(self.bastion_rows)
        outer.addLayout(controls)
        self.grid = ConnectionGrid(lambda: self.store.profile, lambda: self.bulk_protocol.currentText(), key_library=self.key_library)
        self.grid.bastionVisibilityChanged.connect(self.sync_bastion_button)
        self.grid.set_details(self.details.isChecked())
        self.grid.setAccessibleName("일괄 연결 입력 표")
        outer.addWidget(self.grid, 1)
        hints = QHBoxLayout()
        hints.addWidget(label("Enter 다음 행   드래그 복사   Ctrl+드래그 +1   행 번호: 연결 전체 선택", "muted"), 1)
        outer.addLayout(hints)
        actions = QHBoxLayout()
        actions.addWidget(button("CSV 불러오기", self.import_csv))
        actions.addWidget(button("가져오기", self.import_package))
        export = button("내보내기 (키 포함)", self.export_current_package)
        export.setToolTip("연결의 키 파일을 ZIP에 포함합니다. 내보낸 파일은 암호화되지 않습니다.")
        actions.addWidget(export)
        actions.addStretch(1)
        self.bulk_action = button("일괄 추가", self.register_bulk, "primary")
        actions.addWidget(self.bulk_action)
        outer.addLayout(actions)
        self.pages.addWidget(page)

    def sync_bastion_button(self, expanded):
        self.bastion_rows.blockSignals(True)
        self.bastion_rows.setChecked(expanded)
        self.bastion_rows.setText("Bastion 모두 접기" if expanded else "Bastion 모두 펼치기")
        self.bastion_rows.blockSignals(False)

    def export_current_package(self):
        def action():
            self.grid.commit_editor()
            rows = self.grid.rows() if self.pages.currentIndex() == 1 else [{**self.single_form.get_row(), "host": self.host.text()}]
            self.export_package_rows(rows)
        self.perform(action)

    def export_package_rows(self, rows):
        rows = core.validate_batch(rows, check_keys=True)
        path, _ = QFileDialog.getSaveFileName(self, "연결 내보내기 — 키 파일 포함", "연결.mobaquick.zip", "연결 묶음 (*.mobaquick.zip *.zip)")
        if path:
            result = portable.export_bundle(path, rows, self.store.state["favorite_keys"], overwrite=True)
            self.set_status(f"연결 {result['connections']}개와 키 {result['keys']}개를 내보냈습니다.")

    def import_package(self):
        if self.registration_thread is not None:
            self.set_status("세션 추가가 끝난 뒤 가져오세요.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "연결 가져오기", "", "연결 묶음 (*.mobaquick.zip *.zip);;모든 파일 (*)")
        if not path:
            return
        def action():
            bundle = portable.read_bundle(path)
            text = f"연결 {len(bundle.rows)}개와 키 {len(bundle.keys)}개를 가져올까요?\n현재 입력 표를 바꿉니다. 키는 이 PC에 보관됩니다."
            if QMessageBox.question(self, "연결 가져오기", text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
                return
            rows = portable.install_bundle(bundle, self.store)
            self.grid.remember()
            self.grid.bastion_visible = False
            self.grid.expanded_rows.clear()
            self.grid.set_rows(rows)
            self.key_library.changed.emit()
            self.select_page(1)
            self.set_status(f"연결 {len(rows)}개를 가져왔습니다. 확인 후 일괄 추가하세요.")
        self.perform(action)

    def make_settings(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(label("기본값 설정", "title"), 1)
        self.settings_protocol = QComboBox()
        self.settings_protocol.addItems(["SSH", "RDP"])
        self.settings_protocol.setAccessibleName("기본값 연결 방식")
        top.addWidget(self.settings_protocol)
        outer.addLayout(top)
        exe_row = QHBoxLayout()
        self.exe_field = line("MobaXterm 실행 파일")
        self.exe_field.setAccessibleName("MobaXterm 실행 파일")
        exe_row.addWidget(self.exe_field, 1)
        exe_row.addWidget(button("실행 파일 선택", self.pick_exe))
        outer.addLayout(exe_row)
        shell, box = card()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.settings_form = ConnectionForm(key_library=self.key_library)
        self.settings_form.fields["name"].setDisabled(True)
        self.settings_form.fields["name"].setPlaceholderText("연결 이름은 IP로 자동 생성")
        scroll.setWidget(self.settings_form)
        box.addWidget(scroll, 1)
        outer.addWidget(shell, 1)
        self.settings_draft = copy.deepcopy(self.store.profile)
        self.settings_kind = "SSH"
        self.settings_protocol.currentTextChanged.connect(self.switch_settings_kind)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(button("기본값 저장", self.save_settings, "primary"))
        outer.addLayout(foot)
        self.pages.addWidget(page)

    def refresh_profiles(self):
        self.profiles.blockSignals(True)
        self.profiles.clear()
        for name in self.store.state["profiles"]:
            self.profiles.addItem(name)
        self.profiles.setCurrentText(self.store.state["active_profile"])
        self.profiles.blockSignals(False)
        self.apply_single_defaults()

    def manage_keys(self):
        dialog = FavoriteKeysDialog(self.key_library, self)
        dialog.exec()
        dialog.deleteLater()

    def change_profile(self, name):
        if not name:
            return
        self.store.state["active_profile"] = name
        self.store.save()
        self.apply_single_defaults()
        rows = self.grid.rows()
        self.grid.set_rows([r if r["host"] else core.new_row(self.store.profile, r["protocol"] if r["protocol"] in core.DEFAULTS else "SSH") for r in rows])
        self.settings_draft = copy.deepcopy(self.store.profile)
        self.settings_kind = self.settings_protocol.currentText()
        self.settings_form.set_row({"protocol": self.settings_kind, **self.settings_draft[self.settings_kind]})
        self.set_status(f"{name} 기본값을 적용했습니다. 이미 입력한 일괄 행은 유지됩니다.")

    def new_profile(self):
        name, accepted = QInputDialog.getText(self, "기본값 추가", "프로필 이름")
        if accepted and name.strip():
            name = name.strip()
            if name in self.store.state["profiles"]:
                self.set_status("같은 이름의 프로필이 있습니다.", True)
                return
            self.store.state["profiles"][name] = copy.deepcopy(self.store.profile)
            self.store.state["active_profile"] = name
            self.store.save()
            self.refresh_profiles()
            self.select_page(2)

    def apply_single_defaults(self):
        if hasattr(self, "single_form"):
            self.single_form.set_row(core.new_row(self.store.profile, self.single_protocol.currentText()))

    def select_page(self, index):
        if index and self.height() < 520:
            self.resize(self.width(), 520)
        elif index == 0 and self.height() == 520:
            self.resize(self.width(), 440)
        self.pages.setCurrentIndex(index)
        for i, tab in enumerate(self.tabs):
            tab.setChecked(index == i)
        if index == 0:
            QTimer.singleShot(0, self.host.setFocus)
        elif index == 1:
            QTimer.singleShot(0, self.grid.setFocus)
        else:
            self.settings_draft = copy.deepcopy(self.store.profile)
            self.settings_kind = self.settings_protocol.currentText()
            self.settings_form.set_row({"protocol": self.settings_kind, **self.settings_draft[self.settings_kind]})

    def switch_settings_kind(self, kind):
        row = self.settings_form.get_row()
        self.settings_draft[self.settings_kind] = {f: row.get(f, "") for f in core.DEFAULTS[self.settings_kind]}
        self.settings_kind = kind
        self.settings_form.set_row({"protocol": kind, **self.settings_draft[kind]})

    def save_settings(self):
        def action():
            row = self.settings_form.get_row()
            self.settings_draft[self.settings_kind] = {f: row.get(f, "") for f in core.DEFAULTS[self.settings_kind]}
            for kind, values in self.settings_draft.items():
                core.normalize({**values, "protocol": kind, "host": "192.0.2.1"}, check_keys=True)
            exe = self.exe_field.text().strip().strip('"')
            if exe:
                core.launch_arguments(exe, self.store.root / "placeholder.ini")
            self.store.state["profiles"][self.store.state["active_profile"]] = copy.deepcopy(self.settings_draft)
            self.store.state["moba_exe"] = exe
            self.store.save()
            if self.hotkey:
                self.hotkey.selected_moba = exe
            self.change_profile(self.store.state["active_profile"])
            self.set_status("기본값을 저장했습니다. 다음 연결부터 자동으로 채워집니다.")
            self.select_page(0)
        self.perform(action)

    def save_single_defaults(self):
        def action():
            row = self.single_form.get_row()
            core.normalize({**row, "host": "192.0.2.1"}, check_keys=True)
            kind = row["protocol"]
            self.store.profile[kind] = {f: row.get(f, "") for f in core.DEFAULTS[kind]}
            self.store.save()
            self.set_status(f"{self.store.state['active_profile']}의 {kind} 기본값을 저장했습니다.")
        self.perform(action)

    def pick_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, "MobaXterm 실행 파일 선택", "", "MobaXterm (*.exe)")
        if path:
            self.exe_field.setText(path.replace("/", "\\"))

    def perform(self, callback):
        try:
            callback()
        except (ValueError, OSError) as exc:
            self.set_status(str(exc), True)
            return False
        return True

    @Slot(str)
    def set_status(self, text, error=False):
        self.status.setText(text)
        self.status.setVisible(bool(text))
        self.status.setStyleSheet("color:#ffb1c8;" if error else "color:#b9afd0;")

    def start_registration(self, rows):
        if self.registration_thread is not None:
            self.set_status("세션 추가가 진행 중입니다.")
            return
        if self.dry_run:
            self.store.add(rows)
            self.set_status(f"{len(rows)}개 세션을 추가했습니다.")
            return
        preferred = getattr(self.hotkey, "last_moba_pid", None)
        target = integration.find_target(self.store.state["moba_exe"], self.store.state.get("moba_target"), preferred)
        # Check the local history before closing the user's original application.
        existing = {(c["folder"].casefold(), c["name"].casefold()): c for c in self.store.state["connections"]}
        for row in rows:
            old = existing.get((row["folder"].casefold(), row["name"].casefold()))
            if old and old != row:
                raise ValueError(f"{row['name']}: 같은 이름의 등록 기록이 있습니다.")
        self.single_action.setEnabled(False)
        self.bulk_action.setEnabled(False)
        self.set_status("기존 MobaXterm에 추가합니다.")
        thread = QThread(self)
        worker = RegistrationWorker(target, rows, self.store.root)
        worker.moveToThread(thread)
        self.registration_thread, self.registration_worker = thread, worker
        self.registration_rows = copy.deepcopy(rows)
        thread.started.connect(worker.run)
        worker.progress.connect(self.set_status)
        worker.finished.connect(self.registration_finished)
        worker.failed.connect(self.registration_failed)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self.registration_cleaned)
        thread.start()

    @Slot(object)
    def registration_finished(self, result):
        try:
            self.store.state["moba_target"] = result["target"]
            self.store.add(self.registration_rows)
            self.set_status(f"기존 MobaXterm에 {len(self.registration_rows)}개 세션을 반영했습니다.")
        except (ValueError, OSError) as exc:
            self.set_status("MobaXterm 반영 완료. 도구 기록 저장 실패: " + str(exc), True)
        self.registration_thread.quit()

    @Slot(str)
    def registration_failed(self, message):
        self.set_status(message, True)
        self.registration_thread.quit()

    @Slot()
    def registration_cleaned(self):
        thread = self.registration_thread
        self.registration_thread = self.registration_worker = None
        self.single_action.setEnabled(True)
        self.bulk_action.setEnabled(True)
        thread.deleteLater()

    def connect_single(self):
        def action():
            row = core.normalize({**self.single_form.get_row(), "host": self.host.text()}, check_keys=True)
            self.start_registration([row])
        self.perform(action)

    def register_bulk(self):
        def action():
            self.grid.commit_editor()
            rows = core.validate_batch(self.grid.rows(), check_keys=True)
            self.start_registration(rows)
        self.perform(action)

    def change_bulk_kind(self, kind):
        if hasattr(self, "grid"):
            self.grid.remember()
            self.grid.set_rows([r if r["host"] else core.new_row(self.store.profile, kind) for r in self.grid.rows()])

    def primary_action(self):
        {0: self.connect_single, 1: self.register_bulk, 2: self.save_settings}[self.pages.currentIndex()]()

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "CSV 불러오기", "", "CSV (*.csv)")
        if not path:
            return
        def action():
            raw = Path(path).read_bytes()
            if len(raw) > 2_000_000:
                raise ValueError("CSV 파일은 2MB 이하만 불러올 수 있습니다.")
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp949")
            aliases = dict(zip(core.HEADERS, core.FIELDS))
            aliases.update({"IP": "host", "IP / 호스트": "host", "호스트": "host", "유형": "protocol", "세션명": "name", "키경로": "key_path"})
            reader = csv.DictReader(text.splitlines())
            rows = []
            for source in reader:
                mapped = {aliases.get(k, k): str(v or "") for k, v in source.items() if k}
                kind = mapped.get("protocol", "SSH").upper() or "SSH"
                if kind not in core.DEFAULTS:
                    raise ValueError("CSV의 방식은 SSH 또는 RDP여야 합니다.")
                rows.append({**core.new_row(self.store.profile, kind), **mapped, "protocol": kind})
                if len(rows) > 2000:
                    raise ValueError("CSV는 최대 2,000행까지 가능합니다.")
            if not rows or not any(r.get("host") for r in rows):
                raise ValueError("CSV에 IP / 호스트 또는 host 열이 필요합니다.")
            self.grid.remember()
            self.grid.set_rows(rows)
            self.set_status(f"{len(rows)}행을 불러왔습니다. 수정 후 일괄 등록하세요.")
        self.perform(action)

    def export_rows(self, rows):
        path, _ = QFileDialog.getSaveFileName(self, "세션 파일 내보내기", "Quick Connect.mxtsessions", "MobaXterm 세션 (*.mxtsessions)")
        if path:
            raw = core.export_bytes(rows)
            # Save dialog provides the explicit overwrite confirmation.
            Path(path).write_bytes(raw)
            self.set_status("세션 파일을 저장했습니다. MobaXterm의 세션 가져오기에 사용할 수 있습니다.")

    def export_bulk(self):
        self.perform(lambda: self.export_rows(core.validate_batch(self.grid.rows(), check_keys=True)))

    def export_saved(self):
        if not self.store.state["connections"]:
            self.set_status("등록한 연결이 없습니다.", True)
            return
        self.perform(lambda: self.export_rows(self.store.state["connections"]))

    def show_popup(self):
        if self.isVisible() and self.isActiveWindow():
            self.hide()
            return
        self.showNormal()
        reveal_window(int(self.winId()))
        self.raise_()
        self.activateWindow()
        if self.pages.currentIndex() == 0:
            self.host.setFocus()
            self.host.selectAll()

    def escape(self):
        for picker in self.findChildren(KeyPicker):
            if picker.combo.completer().popup().isVisible():
                picker.combo.completer().popup().hide()
                return
        if self.grid.drag_seed:
            self.grid.cancel_fill()
        else:
            self.hide()

    def quit_app(self):
        if self.registration_thread is not None:
            self.set_status("세션 추가가 끝난 뒤 종료해주세요.")
            return
        self.quitting = True
        if self.hotkey:
            self.hotkey.stop()
        if self.tray:
            self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        if self.registration_thread is not None:
            self.hide()
            event.ignore()
            return
        if self.tray and not self.quitting:
            self.hide()
            event.ignore()
        else:
            if self.hotkey:
                self.hotkey.stop()
            event.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-hotkey", action="store_true")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--hidden", action="store_true")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Moba Quick Connect")
    app.setOrganizationName("MobaQuickConnect")
    configure_application(app)
    app.setWindowIcon(icon())
    app.setQuitOnLastWindowClosed(False)
    instance_name = "MobaQuickConnect-" + str(os.getlogin()) if os.name == "nt" else "MobaQuickConnect"
    server = QLocalServer()
    socket = QLocalSocket()
    if not args.dry_run:
        socket.connectToServer(instance_name)
        if socket.waitForConnected(500):
            socket.write(b"show")
            socket.waitForBytesWritten(500)
            return 0
        if not server.listen(instance_name):
            QMessageBox.warning(None, "Moba Quick Connect", "이미 실행 중이거나 실행 잠금이 사용 중입니다.")
            return 1
    try:
        store = core.Store(args.data_dir)
    except (OSError, ValueError) as exc:
        QMessageBox.critical(None, "Moba Quick Connect", str(exc))
        return 1
    window = MainWindow(store, dry_run=args.dry_run, no_tray=args.no_tray)
    def received():
        client = server.nextPendingConnection()
        if client:
            client.disconnectFromServer()
            client.deleteLater()
        window.show_popup()
    server.newConnection.connect(received)
    if not args.no_hotkey:
        window.hotkey = ScopedHotkey(sys.executable, store.state["moba_exe"], window)
        window.hotkey.triggered.connect(window.show_popup, Qt.ConnectionType.QueuedConnection)
        try:
            window.hotkey.start()
        except OSError as exc:
            window.set_status(str(exc), True)
    if not args.hidden or not window.tray:
        window.show()
    exit_code = app.exec()
    if window.hotkey:
        window.hotkey.stop()
    server.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
