"""Searchable local key-path favorites. Key file contents are never opened."""
from __future__ import annotations

from pathlib import Path
from difflib import SequenceMatcher
import ntpath

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QApplication, QComboBox, QCompleter, QDialog, QFileDialog,
    QHBoxLayout, QInputDialog, QMessageBox, QPushButton, QStyle, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QVBoxLayout, QWidget)
import themes


def ranked_keys(items, query):
    query = query.strip().casefold()
    ranked = []
    for position, item in enumerate(items):
        alias, path = item['name'].casefold(), item['path'].casefold()
        filename = ntpath.basename(path)
        ratio = SequenceMatcher(None, query, alias).ratio()
        if query == alias or query == path:
            level = 0
        elif alias.startswith(query):
            level = 1
        elif query in alias:
            level = 2
        elif filename.startswith(query):
            level = 3
        elif query in path:
            level = 4
        elif len(query) >= 3 and ratio >= .45:
            level = 5
        else:
            continue
        ranked.append(((level, -ratio, abs(len(alias) - len(query)), alias, path, position), item))
    return [item for _, item in sorted(ranked, key=lambda pair: pair[0])]


class KeyLibrary(QObject):
    changed = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store

    def remember(self, path, parent, *, ask=True):
        if self.store.favorite_key(path):
            return False
        if ask and QMessageBox.question(parent, "즐겨찾는 키", "이 키를 즐겨찾기에 등록할까요?\n" + path,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
            return False
        try:
            added = self.store.add_favorite_key(path)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(parent, "즐겨찾기 저장 실패", str(exc))
            return False
        if added:
            self.changed.emit()
        return added


class SearchCombo(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(themes.color(self, '#bca4e8'), 1.5))
        x, y = self.width() - 15, self.height() // 2
        painter.drawLine(x - 4, y - 2, x, y + 2)
        painter.drawLine(x, y + 2, x + 4, y - 2)


class KeyPicker(QWidget):
    advance = Signal()
    finished = Signal()

    def __init__(self, library, parent=None, *, table_editor=False):
        super().__init__(parent)
        self.library = library
        self.browsing = False
        self.closed = False
        self.table_editor = table_editor
        self._selected_path = ''
        self._editing_query = False
        self._search_pending = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.combo = SearchCombo(self)
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.setMinimumWidth(0)
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(10)
        self.combo.setMaxVisibleItems(10)
        self.combo.lineEdit().setPlaceholderText("키 검색 또는 경로 입력")
        self.combo.setAccessibleName("즐겨찾는 키 검색")
        self.combo.activated.connect(self.choose_index)
        self.search_model = QStandardItemModel(self)
        completer = QCompleter(self.search_model, self.combo)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.combo.setCompleter(completer)
        self.combo.view().setMinimumWidth(460)
        completer.popup().setMinimumWidth(460)
        completer.activated[str].connect(self.choose_completion)
        self.combo.lineEdit().textEdited.connect(self.query_edited)
        row.addWidget(self.combo, 1)
        self.browse_button = QPushButton(self)
        self.browse_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.browse_button.setAccessibleName("키 파일 찾아보기")
        self.browse_button.setToolTip("키 파일 찾아보기")
        self.browse_button.setFixedWidth(32)
        self.browse_button.clicked.connect(self.browse)
        row.addWidget(self.browse_button)
        self.setFocusProxy(self.combo)
        self.combo.installEventFilter(self)
        self.combo.lineEdit().installEventFilter(self)
        completer.popup().installEventFilter(self)
        self.browse_button.installEventFilter(self)
        if library:
            library.changed.connect(self.refresh)
        self.refresh()

    def text(self):
        if not self._editing_query:
            return self._selected_path
        return self.combo.currentText()

    def setText(self, text):
        self._selected_path = str(text)
        self._editing_query = False
        display = self.library.store.key_label(text) if self.library else str(text)
        self.combo.setCurrentIndex(-1)
        self.combo.setEditText(display)
        self.combo.setToolTip(str(text))

    def refresh(self):
        text = self.text()
        was_query = self._editing_query
        self.combo.blockSignals(True)
        self.combo.clear()
        if self.library:
            for item in self.library.store.state["favorite_keys"]:
                self.combo.addItem(item["name"] + "  —  " + item["path"], item["path"])
                self.combo.setItemData(self.combo.count() - 1, item["path"], Qt.ItemDataRole.ToolTipRole)
        self.setText(text)
        self.combo.blockSignals(False)
        if was_query:
            self.query_edited(text)

    def choose_index(self, index):
        if index >= 0:
            self.setText(self.combo.itemData(index) or "")
            QTimer.singleShot(0, self.settle_display)

    def choose_completion(self, text):
        for row in range(self.search_model.rowCount()):
            item = self.search_model.item(row)
            if item.text() == text:
                self.setText(item.data(Qt.ItemDataRole.UserRole))
                QTimer.singleShot(0, self.settle_display)
                return

    def settle_display(self):
        if self.closed or self._editing_query:
            return
        try:
            self.setText(self._selected_path)
        except RuntimeError:
            pass

    def query_edited(self, text):
        self._editing_query = True
        if not self._search_pending:
            self._search_pending = True
            QTimer.singleShot(0, self.show_matches)

    def show_matches(self):
        self._search_pending = False
        if self.closed or not self._editing_query:
            return
        query = self.combo.currentText().strip()
        self.search_model.clear()
        matches = ranked_keys(self.library.store.state['favorite_keys'], query) if self.library and query else []
        for favorite in matches:
            item = QStandardItem(favorite['name'] + '  —  ' + favorite['path'])
            item.setData(favorite['path'], Qt.ItemDataRole.UserRole)
            item.setToolTip(favorite['path'])
            self.search_model.appendRow(item)
        completer = self.combo.completer()
        if matches:
            completer.setCompletionPrefix(query)
            completer.setCurrentRow(0)
            completer.complete()
            index = completer.completionModel().index(0, 0)
            completer.popup().setCurrentIndex(index)
        else:
            completer.popup().hide()

    def accept_match(self):
        popup = self.combo.completer().popup()
        index = popup.currentIndex()
        if popup.isVisible() and index.isValid():
            path = index.data(Qt.ItemDataRole.UserRole)
            if path:
                self.setText(path)
                popup.hide()
                QTimer.singleShot(0, self.settle_display)
                return True
        return False

    def browse(self):
        self.browsing = True
        try:
            path, _ = QFileDialog.getOpenFileName(self, "키 파일 선택", self.text(), "모든 파일 (*)")
            if path:
                path = str(Path(path))
                self.setText(path)
                if self.library:
                    self.library.remember(path, self)
        finally:
            self.browsing = False
            self.combo.setFocus()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
            if self._search_pending:
                self.show_matches()
            if self.accept_match():
                return True
            if self.table_editor:
                self.advance.emit()
                return True
        if self.table_editor:
            if event.type() == QEvent.Type.FocusOut:
                QTimer.singleShot(0, self.finish_if_outside)
        return super().eventFilter(watched, event)

    def finish_if_outside(self):
        if self.closed or self.browsing:
            return
        try:
            if self.combo.completer().popup().isVisible():
                return
            focus = QApplication.focusWidget()
            if focus != self and (focus is None or not self.isAncestorOf(focus)):
                self.finished.emit()
        except RuntimeError:
            pass  # The view may already have destroyed a finished cell editor.


class FavoriteKeysDialog(QDialog):
    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.setWindowTitle("즐겨찾는 키")
        self.resize(650, 300)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["이름", "키 파일 경로"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 170)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        for title, handler in (("+ 파일 추가", self.add_file), ("이름 변경", self.rename), ("목록에서 제거", self.remove)):
            button = QPushButton(title, self)
            button.clicked.connect(handler)
            actions.addWidget(button)
        actions.addStretch(1)
        close = QPushButton("닫기", self)
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)
        library.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.table.setRowCount(len(self.library.store.state["favorite_keys"]))
        for row, item in enumerate(self.library.store.state["favorite_keys"]):
            for col, key in enumerate(("name", "path")):
                cell = QTableWidgetItem(item[key])
                cell.setToolTip(item[key])
                self.table.setItem(row, col, cell)

    def selected(self):
        row = self.table.currentRow()
        return self.library.store.state["favorite_keys"][row] if row >= 0 else None

    def add_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "키 파일 선택", "", "모든 파일 (*)")
        if path:
            self.library.remember(str(Path(path)), self, ask=False)

    def rename(self):
        item = self.selected()
        if item:
            name, ok = QInputDialog.getText(self, "키 이름 변경", "이름", text=item["name"])
            if ok:
                self.mutate(lambda: self.library.store.rename_favorite_key(item["path"], name))

    def remove(self):
        item = self.selected()
        if item:
            self.mutate(lambda: self.library.store.remove_favorite_key(item["path"]))

    def mutate(self, callback):
        try:
            callback()
            self.library.changed.emit()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "즐겨찾기 저장 실패", str(exc))
