"""세이버자동조회 조회 노선 관리 창."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import sabre_core as c
from sabre_ui import (
    BASE_DIR, COL_WIDTHS, ENABLED_CHOICES, FARE_CHOICES, FIELDS,
    MANAGE_COLS, MANAGE_HEADERS, bind_alt_enter, format_date_edit,
    matches_route_query, show,
)

if TYPE_CHECKING:
    from sabre_app import App


class InlineLineEdit(QLineEdit):
    """인라인 편집용 입력칸: ↑=맨 앞, ↓=맨 끝, Enter=저장, Esc=취소."""

    def __init__(self, text: str, on_commit, on_cancel, parent: QWidget | None = None, on_multi_paste=None):
        super().__init__(text, parent)
        self._on_commit = on_commit
        self._on_cancel = on_cancel
        self._on_multi_paste = on_multi_paste
        self.setStyleSheet(
            "QLineEdit { border: 1.5px solid #2563eb; border-radius: 4px; padding: 1px 5px; background: #ffffff; }"
        )

    def keyPressEvent(self, event) -> None:
        if self._on_multi_paste and event.matches(QKeySequence.StandardKey.Paste):
            clip = QApplication.clipboard().text()
            if "\t" in clip or "\n" in clip:
                self._on_multi_paste(clip)
                event.accept()
                return
        key = event.key()
        if key == Qt.Key.Key_Down:
            self.deselect()
            self.setCursorPosition(len(self.text()))
            event.accept()
            return
        if key == Qt.Key.Key_Up:
            self.deselect()
            self.setCursorPosition(0)
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.AltModifier):
            self._on_commit()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self._on_cancel()
            event.accept()
            return
        super().keyPressEvent(event)


class InlineComboBox(QComboBox):
    """인라인 편집용 드롭박스: Enter=저장, Esc=취소."""

    def __init__(self, items: tuple[str, ...], current: str, on_commit, on_cancel, parent: QWidget | None = None):
        super().__init__(parent)
        self._on_commit = on_commit
        self._on_cancel = on_cancel
        self.addItems(list(items))
        idx = self.findText(current)
        if idx >= 0:
            self.setCurrentIndex(idx)
        self.setStyleSheet(
            "QComboBox { border: 1.5px solid #2563eb; border-radius: 4px; padding: 1px 4px; background: #ffffff; }"
        )

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.AltModifier):
            self._on_commit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._on_cancel()
            event.accept()
            return
        super().keyPressEvent(event)


class ManageWindow(QDialog):
    """설정 > 조회 노선 관리 창 (검색 + 더블클릭/F2 인라인 편집 + 우클릭 메뉴 + CSV)."""

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.setWindowTitle("조회 노선 관리")
        w, h = 1620, 840
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            w = min(w, max(1080, avail.width() - 60))
            h = min(h, max(560, avail.height() - 80))
        self.resize(w, h)
        self.edit_state: dict | None = None
        bind_alt_enter(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        search_lbl = QLabel("노선 검색")
        search_lbl.setObjectName("FieldLabel")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("노선그룹, 출발/도착지, 항공사, 출·귀국편 검색")
        self.search_edit.setFixedWidth(320)
        self.search_edit.textChanged.connect(self.refresh_table)
        self.count_lbl = QLabel()
        self.count_lbl.setObjectName("SummaryPill")
        top.addWidget(search_lbl)
        top.addWidget(self.search_edit)
        top.addStretch()
        top.addWidget(self.count_lbl)
        lay.addLayout(top)

        self.table = QTableWidget(0, len(MANAGE_COLS))
        self.table.setObjectName("ManageTable")
        self.table.setHorizontalHeaderLabels(list(MANAGE_HEADERS))
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalScrollBar().setSingleStep(28)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_context_menu)
        self.table.cellDoubleClicked.connect(self.on_cell_double_click)
        self.table.viewport().installEventFilter(self)
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, w in enumerate(COL_WIDTHS):
            self.table.setColumnWidth(col, w)

        table_card = QFrame()
        table_card.setObjectName("TableCard")
        tc_lay = QVBoxLayout(table_card)
        tc_lay.setContentsMargins(1, 1, 1, 1)
        tc_lay.setSpacing(0)
        tc_lay.addWidget(self.table, 1)
        # 노선 수가 많아 표가 꽉 차도 항상 빈 공간 우클릭(노선 추가)이 가능하도록 하단 여유 공간을 둔다.
        self.blank_zone = QFrame()
        self.blank_zone.setObjectName("TableBlankZone")
        self.blank_zone.setFixedHeight(52)
        self.blank_zone.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.blank_zone.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.blank_zone.customContextMenuRequested.connect(self.on_blank_context_menu)
        self.blank_zone.installEventFilter(self)
        tc_lay.addWidget(self.blank_zone)
        lay.addWidget(table_card, 1)

        f2_sc = QShortcut(QKeySequence(Qt.Key.Key_F2), self.table)
        f2_sc.activated.connect(self.on_f2)
        copy_sc = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        copy_sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        copy_sc.activated.connect(self.copy_selected_cells)
        paste_sc = QShortcut(QKeySequence.StandardKey.Paste, self.table)
        paste_sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        paste_sc.activated.connect(self.paste_to_selected_cells)
        blank_paste_sc = QShortcut(QKeySequence.StandardKey.Paste, self.blank_zone)
        blank_paste_sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        blank_paste_sc.activated.connect(lambda: self.paste_to_selected_cells(force_append=True))

        btns = QHBoxLayout()
        btns.setSpacing(8)
        exp_btn = QPushButton("CSV 내보내기")
        imp_btn = QPushButton("CSV 불러오기")
        exp_btn.clicked.connect(self.export_csv)
        imp_btn.clicked.connect(self.import_csv)
        btns.addWidget(exp_btn)
        btns.addWidget(imp_btn)
        btns.addStretch()
        lay.addLayout(btns)

        self.refresh_table()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.table.viewport():
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress and self.edit_state:
                clicked_row = self.table.rowAt(event.position().toPoint().y())
                if clicked_row != self.edit_state["row"]:
                    if not self.commit_row_edit():
                        return True
            elif etype == QEvent.Type.MouseButtonDblClick:
                pos = event.position().toPoint()
                real_row, real_col = self.table.rowAt(pos.y()), self.table.columnAt(pos.x())
                if real_row >= 0:
                    self.start_row_edit(real_row, focus_col=max(0, real_col))
                    return True
        elif obj is self.blank_zone:
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress:
                if self.edit_state and not self.commit_row_edit():
                    return True
                self.table.clearSelection()
                self.table.setCurrentCell(-1, -1)
                self.blank_zone.setFocus()
            elif etype == QEvent.Type.Wheel:
                sb = self.table.verticalScrollBar()
                sb.setValue(sb.value() - int(event.angleDelta().y() * 0.6))
                return True
        return super().eventFilter(obj, event)

    def _row_route_index(self, row: int) -> int | None:
        if row < 0 or row >= self.table.rowCount():
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def refresh_table(self) -> None:
        self.cancel_row_edit()
        query = self.search_edit.text()
        self.table.clearSpans()
        self.table.setRowCount(0)
        shown = 0
        for idx, r in enumerate(self.app.routes):
            if not matches_route_query(r, query):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                ("최저가" if k == "bookingClass" and not show(r, k) else show(r, k))
                for _, k in FIELDS
            ] + ["FARE KRW" if c.route_fare_only(r) else "TOTAL KRW", "사용" if r.get("enabled", True) else "중지"]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, idx)
                self.table.setItem(row, col, item)
            shown += 1
        self._apply_group_spans()
        total = len(self.app.routes)
        self.count_lbl.setText(f"검색 {shown} / {total}개" if query.strip() else f"총 {total}개")

    def _apply_group_spans(self) -> None:
        self.table.clearSpans()
        count = self.table.rowCount()
        even_bg = QBrush(QColor("#ffffff"))
        odd_bg = QBrush(QColor("#f1f5f9"))
        row, band = 0, 0
        while row < count:
            idx = self._row_route_index(row)
            item = self.table.item(row, 0)
            grp = item.text().strip() if (idx is not None and item is not None) else ""
            if not grp:
                bg = odd_bg if band % 2 else even_bg
                for col in range(len(MANAGE_COLS)):
                    cell = self.table.item(row, col)
                    if cell is not None:
                        cell.setBackground(bg)
                band += 1
                row += 1
                continue
            end = row + 1
            while end < count:
                n_idx = self._row_route_index(end)
                n_item = self.table.item(end, 0)
                n_grp = n_item.text().strip() if (n_idx is not None and n_item is not None) else ""
                if n_grp != grp:
                    break
                end += 1
            bg = odd_bg if band % 2 else even_bg
            for r in range(row, end):
                for col in range(len(MANAGE_COLS)):
                    cell = self.table.item(r, col)
                    if cell is not None:
                        cell.setBackground(bg)
            if end - row > 1:
                self.table.setSpan(row, 0, end - row, 1)
            band += 1
            row = end

    def on_cell_double_click(self, row: int, col: int) -> None:
        self.start_row_edit(row, focus_col=col)

    def on_f2(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.start_row_edit(row, focus_col=0)

    def _selected_cell_coords(self) -> list[tuple[int, int]]:
        coords = [(idx.row(), idx.column()) for idx in self.table.selectedIndexes()]
        if not coords:
            r, col = self.table.currentRow(), self.table.currentColumn()
            if r >= 0 and col >= 0:
                coords = [(r, col)]
        return sorted(set(coords))

    def copy_selected_cells(self) -> str:
        if self.edit_state:
            return ""
        coords = self._selected_cell_coords()
        if not coords:
            return ""
        rows = sorted({r for r, _ in coords})
        cols = sorted({col for _, col in coords})
        coord_set = set(coords)
        lines = []
        for r in rows:
            vals = []
            for col in cols:
                if (r, col) in coord_set:
                    item = self.table.item(r, col)
                    vals.append(item.text() if item is not None else "")
                else:
                    vals.append("")
            lines.append("\t".join(vals))
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        return text

    def _handle_inline_multi_paste(self, clip_text: str, start_col: int) -> None:
        state = self.edit_state
        if not state:
            return
        is_new = state["index"] is None
        r0 = state["row"]
        self.cancel_row_edit()
        self.paste_to_selected_cells(
            clip_text,
            force_append=is_new,
            start_row=None if is_new else r0,
            start_col=start_col,
        )

    def paste_to_selected_cells(self, clip_text: str | None = None, *, force_append: bool = False,
                                start_row: int | None = None, start_col: int = 0) -> bool:
        if self.edit_state:
            return False
        raw_text = QApplication.clipboard().text() if clip_text is None else clip_text
        if not raw_text:
            return False
        rows_in = [line.split("\t") for line in raw_text.splitlines()]
        while rows_in and rows_in[-1] == [""]:
            rows_in.pop()
        if rows_in and rows_in[0] and rows_in[0][0].strip() in ("노선그룹", "routeGroup"):
            rows_in = rows_in[1:]
        if not rows_in:
            return False
        coords = self._selected_cell_coords()
        if not force_append and start_row is None and not coords and len(rows_in) == 1 and len(rows_in[0]) == 1:
            return False
        # force_append(빈 공간/신규 행 붙여넣기)는 복사된 모든 행을 신규 노선으로 추가한다.
        if not force_append and start_row is None and len(rows_in) == 1 and len(rows_in[0]) == 1:
            targets = [(r, col, rows_in[0][0].strip()) for r, col in coords]
            anchor_r, anchor_c = coords[0]
        else:
            if force_append:
                r0, c0 = self.table.rowCount(), start_col
            elif start_row is not None:
                r0, c0 = start_row, start_col
            elif coords:
                r0, c0 = min(r for r, _ in coords), min(col for _, col in coords)
            else:
                r0, c0 = self.table.rowCount(), start_col
            anchor_r, anchor_c = r0, c0
            targets = []
            for dr, vals in enumerate(rows_in):
                r = r0 + dr
                for dc, val in enumerate(vals):
                    col = c0 + dc
                    if col < len(MANAGE_COLS):
                        targets.append((r, col, val.strip()))

        drafts: dict[tuple[str, int], dict] = {}
        for r, col, val in targets:
            if r < self.table.rowCount():
                idx = self._row_route_index(r)
                if idx is None:
                    continue
                dkey = ("edit", idx)
                if dkey not in drafts:
                    src = self.app.routes[idx]
                    drafts[dkey] = {
                        **{k: show(src, k) for _, k in FIELDS},
                        "region": src.get("region", ""),
                        "fareOnly": c.route_fare_only(src),
                        "enabled": bool(src.get("enabled", True)),
                        "_orig_dest": str(src.get("destination", "")).upper(),
                    }
            else:
                dkey = ("new", r)
                if dkey not in drafts:
                    drafts[dkey] = {
                        **{k: ("4" if k == "pax" else "Y" if k == "bookingClass" else "") for _, k in FIELDS},
                        "fareOnly": True,
                        "enabled": True,
                        "_orig_dest": "",
                    }
            key = MANAGE_COLS[col]
            if key == "fareOnly":
                drafts[dkey]["fareOnly"] = c._parse_csv_bool(
                    val, default=True, false_tokens=("TOTAL KRW", "TOTAL", "총액", "총액(텍스포함)", "FALSE", "0", "N", "NO", "해제")
                )
            elif key == "enabled":
                drafts[dkey]["enabled"] = c._parse_csv_bool(
                    val, default=True, false_tokens=("중지", "미사용", "FALSE", "0", "N", "NO")
                )
            elif key in ("startDate", "endDate"):
                drafts[dkey][key] = c._normalize_csv_date(val)
            else:
                drafts[dkey][key] = val
        if not drafts:
            return False

        edited: dict[int, dict] = {}
        added: list[dict] = []
        for (kind, key_id), d in sorted(drafts.items(), key=lambda kv: (0 if kv[0][0] == "edit" else 1, kv[0][1])):
            orig_dest = d.pop("_orig_dest")
            if kind == "edit" and orig_dest != str(d.get("destination", "")).strip().upper():
                d.pop("region", None)
            try:
                norm = c.normalize_route(d, allow_partial=True)
            except ValueError as exc:
                QMessageBox.critical(self, "붙여넣기 오류", f"입력값 오류: {exc}")
                return False
            if kind == "edit":
                edited[key_id] = norm
            else:
                added.append(norm)
        for idx, route in edited.items():
            self.app.routes[idx] = route
        if added:
            self.app.routes.extend(added)
            if self.search_edit.text().strip():
                self.search_edit.blockSignals(True)
                self.search_edit.setText("")
                self.search_edit.blockSignals(False)
        self.app.save_routes_and_refresh()
        if 0 <= anchor_r < self.table.rowCount() and 0 <= anchor_c < len(MANAGE_COLS):
            self.table.setCurrentCell(anchor_r, anchor_c)
            item = self.table.item(anchor_r, anchor_c)
            if item is not None:
                self.table.scrollToItem(item)
        return True

    def build_context_menu(self, row: int) -> QMenu:
        menu = QMenu(self.table)
        if 0 <= row < self.table.rowCount() and self._row_route_index(row) is not None:
            self.table.selectRow(row)
            self.table.setCurrentCell(row, 0)
            menu.addAction("노선 복사", self.copy_route_row)
            menu.addAction("노선 삭제", self.delete_route_row)
        else:
            menu.addAction("노선 추가", self.add_route_row)
            menu.addAction("붙여넣기로 노선 추가", lambda: self.paste_to_selected_cells(force_append=True))
        return menu

    def on_context_menu(self, pos: QPoint) -> None:
        row = self.table.rowAt(pos.y())
        if self.edit_state and row != self.edit_state["row"] and not self.commit_row_edit():
            return
        menu = self.build_context_menu(row)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def on_blank_context_menu(self, pos: QPoint) -> None:
        if self.edit_state and not self.commit_row_edit():
            return
        menu = self.build_context_menu(-1)
        menu.exec(self.blank_zone.mapToGlobal(pos))

    def add_route_row(self) -> None:
        if self.edit_state and not self.commit_row_edit():
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        defaults = ["", "", "", "", "", "", "", "", "", "4", "Y", "FARE KRW", "사용"]
        for col, val in enumerate(defaults):
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if col == 0:
                item.setData(Qt.ItemDataRole.UserRole, None)
            self.table.setItem(row, col, item)
        self.table.selectRow(row)
        self.table.scrollToItem(self.table.item(row, 0))
        self.start_row_edit(row, focus_col=0)

    def start_row_edit(self, row: int, focus_col: int = 0) -> None:
        if self.edit_state:
            if self.edit_state["row"] == row:
                w = self.edit_state["widgets"].get(MANAGE_COLS[focus_col])
                if w is not None:
                    w.setFocus()
                return
            if not self.commit_row_edit():
                return
        if row < 0 or row >= self.table.rowCount():
            return
        # 인라인 편집 중에는 병합된 노선그룹을 개별 행으로 펼쳐 개별 수정할 수 있게 한다.
        self.table.clearSpans()
        index = self._row_route_index(row)
        if index is not None:
            route = self.app.routes[index]
            init = {k: show(route, k) for _, k in FIELDS}
            init["fareOnly"] = "FARE KRW" if c.route_fare_only(route) else "TOTAL KRW"
            init["enabled"] = "사용" if route.get("enabled", True) else "중지"
        else:
            init = {k: ("4" if k == "pax" else "Y" if k == "bookingClass" else "") for _, k in FIELDS}
            init["fareOnly"] = "FARE KRW"
            init["enabled"] = "사용"

        widgets: dict[str, QWidget] = {}
        for col, key in enumerate(MANAGE_COLS):
            if key == "fareOnly":
                w: QWidget = InlineComboBox(FARE_CHOICES, init[key], self.commit_row_edit, self.cancel_row_edit, self.table)
            elif key == "enabled":
                w = InlineComboBox(ENABLED_CHOICES, init[key], self.commit_row_edit, self.cancel_row_edit, self.table)
            else:
                w = InlineLineEdit(
                    init[key],
                    self.commit_row_edit,
                    self.cancel_row_edit,
                    self.table,
                    on_multi_paste=lambda clip, c_idx=col: self._handle_inline_multi_paste(clip, c_idx),
                )
                if key in ("startDate", "endDate"):
                    w.editingFinished.connect(lambda e=w: format_date_edit(e))
            self.table.setCellWidget(row, col, w)
            widgets[key] = w
        self.edit_state = {"row": row, "index": index, "widgets": widgets}
        target_key = MANAGE_COLS[focus_col] if 0 <= focus_col < len(MANAGE_COLS) else MANAGE_COLS[0]
        target = widgets[target_key]
        target.setFocus()
        if isinstance(target, QLineEdit):
            target.selectAll()

    def cancel_row_edit(self) -> None:
        state = self.edit_state
        if not state:
            return
        self.edit_state = None
        row = state["row"]
        for col in range(len(MANAGE_COLS)):
            if 0 <= row < self.table.rowCount():
                self.table.removeCellWidget(row, col)
        if state["index"] is None and 0 <= row < self.table.rowCount():
            self.table.removeRow(row)
        self._apply_group_spans()

    def commit_row_edit(self) -> bool:
        state = self.edit_state
        if not state:
            return True
        widgets = state["widgets"]
        raw = {k: widgets[k].text() for _, k in FIELDS}
        index = state["index"]
        if index is None and not any(raw.get(k, "").strip() for _, k in FIELDS if k not in ("pax", "bookingClass")):
            QMessageBox.warning(
                self,
                "미저장 안내",
                "아직 저장되지 않았습니다.\n입력 없이 나가면 추가한 빈 노선 행이 삭제됩니다.",
            )
            self.cancel_row_edit()
            return True
        if index is not None:
            prev = self.app.routes[index]
            if prev.get("destination", "").upper() == raw.get("destination", "").strip().upper() and prev.get("region"):
                raw["region"] = prev["region"]
        fare_only = widgets["fareOnly"].currentText() != "TOTAL KRW"
        enabled = widgets["enabled"].currentText() != "중지"
        try:
            route = c.normalize_route({**raw, "fareOnly": fare_only, "enabled": enabled}, allow_partial=True)
        except ValueError as exc:
            QMessageBox.critical(self, "입력 오류", str(exc))
            return False
        self.cancel_row_edit()
        if index is None:
            self.app.routes.append(route)
            if self.search_edit.text().strip() and not matches_route_query(route, self.search_edit.text()):
                self.search_edit.blockSignals(True)
                self.search_edit.setText("")
                self.search_edit.blockSignals(False)
        else:
            self.app.routes[index] = route
        self.app.save_routes_and_refresh()
        return True

    def copy_route_row(self) -> None:
        if self.edit_state and not self.commit_row_edit():
            return
        row = self.table.currentRow()
        idx = self._row_route_index(row)
        if idx is None:
            QMessageBox.information(self, "안내", "복사할 노선을 먼저 선택하세요.")
            return
        src = self.app.routes[idx]
        new_idx = idx + 1
        self.app.routes.insert(new_idx, {**src, "days": list(src["days"])})
        self.app.save_routes_and_refresh()
        for r in range(self.table.rowCount()):
            if self._row_route_index(r) == new_idx:
                self.table.selectRow(r)
                self.table.setCurrentCell(r, 0)
                self.table.scrollToItem(self.table.item(r, 0))
                self.table.setFocus()
                break

    def delete_route_row(self) -> None:
        self.cancel_row_edit()
        row = self.table.currentRow()
        idx = self._row_route_index(row)
        if idx is None:
            return
        ans = QMessageBox.question(self, "삭제", "선택한 노선을 삭제할까요?")
        if ans == QMessageBox.StandardButton.Yes:
            del self.app.routes[idx]
            self.app.save_routes_and_refresh()

    def export_csv(self) -> None:
        if self.edit_state and not self.commit_row_edit():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "노선 목록 CSV 내보내기", str(BASE_DIR / "sabre-routes.csv"), "CSV 파일 (*.csv);;모든 파일 (*.*)"
        )
        if not path:
            return
        try:
            c.export_routes_csv(Path(path), self.app.routes)
        except OSError as exc:
            QMessageBox.critical(self, "CSV 내보내기 오류", str(exc))
            return
        QMessageBox.information(self, "완료", f"{len(self.app.routes)}개 노선을 CSV로 내보냈습니다.\n{path}")

    def import_csv(self) -> None:
        self.cancel_row_edit()
        path, _ = QFileDialog.getOpenFileName(
            self, "노선 목록 CSV 불러오기", str(BASE_DIR), "CSV 파일 (*.csv);;모든 파일 (*.*)"
        )
        if not path:
            return
        try:
            routes = c.import_routes_csv(Path(path))
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "CSV 불러오기 오류", str(exc))
            return
        ans = QMessageBox.question(
            self, "CSV 불러오기", f"{len(routes)}개 노선을 불러와 현재 목록({len(self.app.routes)}개)을 교체할까요?"
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.app.routes = routes
        self.app.save_routes_and_refresh()
        QMessageBox.information(self, "완료", f"{len(routes)}개 노선을 반영했습니다.")

    def closeEvent(self, event) -> None:
        if self.edit_state and not self.commit_row_edit():
            event.ignore()
            return
        self.cancel_row_edit()
        event.accept()
