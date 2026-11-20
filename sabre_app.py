"""세이버자동조회 화면 (PySide6 Qt6 + QSS): 자동조회 + 설정(조회 노선 관리/로그인/저장경로)."""
from __future__ import annotations

import calendar
import json
import os
import re
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import sabre_core as c
import sabre_terminal as t

BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
ROUTES_PATH = BASE_DIR / "sabre-routes.json"
CONFIG_PATH = BASE_DIR / "sabre-config.json"
CRED_KEYS = ("agentId", "password", "pcc")
FIELDS = (
    ("노선그룹", "routeGroup"),
    ("출발지", "origin"),
    ("도착지", "destination"),
    ("항공사", "airline"),
    ("출국편", "depFlight"),
    ("귀국편", "retFlight"),
    ("항공일수(+N)", "days"),
    ("조회종료일", "endDate"),
    ("조회인원", "pax"),
    ("조회클래스", "bookingClass"),
)
MANAGE_COLS = tuple(k for _, k in FIELDS) + ("fareOnly", "enabled")
MANAGE_HEADERS = tuple(lbl for lbl, _ in FIELDS) + ("운임만", "사용")
COL_WIDTHS = (160, 76, 76, 76, 108, 108, 118, 130, 86, 94, 140, 86)
SEARCH_KEYS = ("routeGroup", "origin", "destination", "airline", "depFlight", "retFlight")
FARE_CHOICES = ("FARE KRW", "TOTAL KRW")
ENABLED_CHOICES = ("사용", "중지")

APP_QSS = """
QMainWindow, QDialog {
    background-color: #f4f6fa;
    color: #0f172a;
    font-family: "Malgun Gothic", "Segoe UI", sans-serif;
    font-size: 13px;
}
QWidget {
    color: #0f172a;
    font-family: "Malgun Gothic", "Segoe UI", sans-serif;
    font-size: 13px;
}
QMenuBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e2e8f0;
    padding: 3px 6px;
}
QMenuBar::item {
    padding: 5px 11px;
    border-radius: 6px;
    background: transparent;
}
QMenuBar::item:selected {
    background-color: #eef2f7;
}
QMenu {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 5px;
}
QMenu::item {
    padding: 7px 24px 7px 12px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: #eff6ff;
    color: #2563eb;
}
QFrame#SurfaceCard, QFrame#PanelBox {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
}
QFrame#PanelHead {
    background-color: #f8fafc;
    border: none;
    border-bottom: 1px solid #e2e8f0;
    border-top-left-radius: 11px;
    border-top-right-radius: 11px;
}
QFrame#RouteCard {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
}
QFrame#RouteCard[active="true"] {
    background-color: #f8fbff;
    border: 1px solid #93c5fd;
}
QFrame#InfoBox {
    background-color: #f8fafc;
    border: 1px solid #dbeafe;
    border-radius: 8px;
}
QLabel#SectionTitle {
    font-size: 13.5px;
    font-weight: 700;
    color: #0f172a;
}
QLabel#MutedLabel {
    font-size: 12px;
    color: #64748b;
}
QLabel#FieldLabel {
    font-size: 12.5px;
    font-weight: 600;
    color: #475569;
}
QLabel#SummaryPill {
    background-color: #eff6ff;
    color: #2563eb;
    border-radius: 11px;
    padding: 3px 10px;
    font-size: 12px;
    font-weight: 600;
}
QLabel#CardTitle {
    font-size: 13px;
    font-weight: 700;
    color: #0f172a;
}
QLineEdit {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    padding: 5px 9px;
    min-height: 20px;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}
QLineEdit:focus {
    border: 1.5px solid #2563eb;
}
QComboBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 3px 8px;
}
QComboBox:focus {
    border: 1.5px solid #2563eb;
}
QPushButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 6px 13px;
    font-size: 12.5px;
    font-weight: 600;
    color: #0f172a;
}
QPushButton:hover {
    background-color: #f8fafc;
    border-color: #94a3b8;
}
QPushButton:pressed {
    background-color: #eef2f7;
}
QPushButton:disabled {
    color: #94a3b8;
    background-color: #f8fafc;
    border-color: #e2e8f0;
}
QPushButton#PrimaryBtn {
    background-color: #2563eb;
    border-color: #2563eb;
    color: #ffffff;
}
QPushButton#PrimaryBtn:hover {
    background-color: #1d4ed8;
    border-color: #1d4ed8;
}
QPushButton#PrimaryBtn:disabled {
    background-color: #93c5fd;
    border-color: #93c5fd;
    color: #ffffff;
}
QPushButton#DangerBtn {
    background-color: #fef2f2;
    border-color: #fecaca;
    color: #dc2626;
}
QPushButton#DangerBtn:hover {
    background-color: #fee2e2;
    border-color: #fca5a5;
}
QPushButton#DangerBtn:disabled {
    background-color: #f8fafc;
    border-color: #e2e8f0;
    color: #94a3b8;
}
QPushButton#SmallBtn {
    padding: 4px 10px;
    border-radius: 7px;
    font-size: 12px;
}
QPushButton#CardToggle {
    background-color: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 2px 9px;
    font-size: 11.5px;
    font-weight: 600;
    color: #334155;
}
QPushButton#CardToggle:hover {
    border-color: #2563eb;
    color: #2563eb;
    background-color: #eff6ff;
}
QPushButton#CardToggle[active="true"] {
    background-color: #eff6ff;
    border-color: #93c5fd;
    color: #2563eb;
}
QCheckBox {
    spacing: 7px;
}
QScrollArea {
    border: none;
    background: transparent;
}
QWidget#CardsHost {
    background: transparent;
}
QScrollBar:vertical {
    width: 9px;
    background: transparent;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    border-radius: 4px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QProgressBar {
    background-color: #e2e8f0;
    border: none;
    border-radius: 4px;
    max-height: 8px;
    min-height: 8px;
}
QProgressBar::chunk {
    background-color: #2563eb;
    border-radius: 4px;
}
QTableWidget {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    gridline-color: #f1f5f9;
    selection-background-color: #eff6ff;
    selection-color: #0f172a;
    outline: 0;
}
QTableWidget::item {
    padding: 4px 6px;
}
QHeaderView::section {
    background-color: #f1f5f9;
    color: #334155;
    font-weight: 700;
    font-size: 12px;
    padding: 7px 4px;
    border: none;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #e2e8f0;
}
QPlainTextEdit {
    background-color: #0f172a;
    color: #e2e8f0;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 8px;
    font-family: "Consolas", "Malgun Gothic", monospace;
    font-size: 12.5px;
}
"""


def read_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def has_saved_login(cfg: dict) -> bool:
    return bool(cfg.get("remember")) and all(str(cfg.get(k) or "").strip() for k in CRED_KEYS)


def mask_secret(value: str, *, full: bool = False) -> str:
    text = str(value or "")
    if not text:
        return ""
    if full:
        return "*" * max(4, len(text))
    if len(text) <= 2:
        return "*" * len(text)
    if len(text) <= 4:
        return f"{text[0]}{'*' * (len(text) - 2)}{text[-1]}"
    return f"{text[:2]}{'*' * (len(text) - 3)}{text[-1]}"


def get_output_root(cfg: dict | None = None, path: Path = CONFIG_PATH) -> Path:
    src = cfg if cfg is not None else read_config(path)
    custom = str(src.get("outputRoot") or "").strip()
    return Path(custom) if custom else c.OUTPUT_ROOT


def save_output_root(folder: str | Path, path: Path = CONFIG_PATH) -> None:
    cfg = read_config(path)
    raw = str(folder or "").strip()
    cfg["outputRoot"] = "" if (not raw or Path(raw) == c.OUTPUT_ROOT) else raw
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_login_config(creds: dict, path: Path = CONFIG_PATH) -> None:
    data = {
        **read_config(path),
        "agentId": str(creds["agentId"]).strip(),
        "password": str(creds["password"]),
        "pcc": str(creds["pcc"]).strip().upper(),
        "remember": True,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clear_remembered_login(path: Path = CONFIG_PATH) -> None:
    cfg = read_config(path)
    if not cfg.get("remember"):
        return
    cfg["remember"] = False
    cfg["password"] = ""
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def show(route: dict, key: str) -> str:
    if key == "routeGroup":
        return c.route_group(route)
    if key == "pax":
        return str(c.route_pax(route))
    if key == "bookingClass":
        return c.route_class(route)
    return ", ".join(map(str, route[key])) if key == "days" else str(route[key])


def add_months(base: date, months: int) -> date:
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(base.day, calendar.monthrange(year, month)[1]))


def matches_route_query(route: dict, query: str) -> bool:
    """노선그룹~귀국편(및 지역명) 범위에서 공백 구분 다중 키워드를 유연하게 검색한다."""
    tokens = query.strip().upper().split()
    if not tokens:
        return True
    hay = " ".join([show(route, k) for k in SEARCH_KEYS] + [c.route_region(route)]).upper()
    compact = re.sub(r"[\s-]+", "", hay)
    return all(tok in hay or re.sub(r"[\s-]+", "", tok) in compact for tok in tokens)


class LoginDialog(QDialog):
    """Sabre 로그인 정보 입력 팝업 (저장 정보 마스킹 표시 + 로그인 정보 기억하기)."""

    def __init__(self, parent: QWidget | None = None, saved_cfg: dict | None = None, submit_label: str = "로그인"):
        super().__init__(parent)
        self.setWindowTitle("Sabre 로그인")
        self.setModal(True)
        self.setFixedWidth(430)
        self.result_data: dict | None = None
        self._saved = saved_cfg or {}
        self.saved_summary_text = ""

        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(18, 16, 18, 16)
        root_lay.setSpacing(12)

        if any(str(self._saved.get(k) or "").strip() for k in CRED_KEYS):
            saved_id = mask_secret(str(self._saved.get("agentId") or "").strip()) or "-"
            saved_pw = mask_secret(str(self._saved.get("password") or ""), full=True) or "-"
            saved_pcc = mask_secret(str(self._saved.get("pcc") or "").strip()) or "-"
            self.saved_summary_text = f"Agent ID: {saved_id}  |  Password: {saved_pw}  |  PCC: {saved_pcc}"
            info_box = QFrame(self)
            info_box.setObjectName("InfoBox")
            info_lay = QVBoxLayout(info_box)
            info_lay.setContentsMargins(10, 8, 10, 8)
            info_lay.setSpacing(3)
            title_lbl = QLabel("현재 저장된 로그인 정보")
            title_lbl.setObjectName("FieldLabel")
            sum_lbl = QLabel(self.saved_summary_text)
            hint_lbl = QLabel("변경할 항목만 새로 입력하세요 (빈칸은 기존 저장값 유지)")
            hint_lbl.setObjectName("MutedLabel")
            info_lay.addWidget(title_lbl)
            info_lay.addWidget(sum_lbl)
            info_lay.addWidget(hint_lbl)
            root_lay.addWidget(info_box)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.agent_edit = QLineEdit()
        self.pw_edit = QLineEdit()
        self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pcc_edit = QLineEdit()
        form.addRow("Agent ID", self.agent_edit)
        form.addRow("Password", self.pw_edit)
        form.addRow("PCC", self.pcc_edit)
        root_lay.addLayout(form)

        self.remember_chk = QCheckBox("로그인 정보 기억하기")
        self.remember_chk.setChecked(bool(self._saved.get("remember", True)))
        root_lay.addWidget(self.remember_chk)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.submit_btn = QPushButton(submit_label)
        self.submit_btn.setObjectName("PrimaryBtn")
        self.submit_btn.setDefault(True)
        self.cancel_btn = QPushButton("취소")
        self.submit_btn.clicked.connect(self.submit)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.submit_btn)
        btn_row.addWidget(self.cancel_btn)
        root_lay.addLayout(btn_row)

        self.agent_edit.setFocus()

    def submit(self) -> None:
        agent_id = self.agent_edit.text().strip() or str(self._saved.get("agentId") or "").strip()
        password = self.pw_edit.text() or str(self._saved.get("password") or "")
        pcc = (self.pcc_edit.text().strip() or str(self._saved.get("pcc") or "").strip()).upper()
        if not agent_id:
            QMessageBox.warning(self, "입력 확인", "Agent ID를 입력하세요.")
            self.agent_edit.setFocus()
            return
        if not password:
            QMessageBox.warning(self, "입력 확인", "Password를 입력하세요.")
            self.pw_edit.setFocus()
            return
        if not pcc:
            QMessageBox.warning(self, "입력 확인", "PCC를 입력하세요.")
            self.pcc_edit.setFocus()
            return
        self.result_data = {
            "agentId": agent_id,
            "password": password,
            "pcc": pcc,
            "remember": self.remember_chk.isChecked(),
        }
        self.accept()


class OutputPathDialog(QDialog):
    """요금조회 엑셀 파일 저장 경로 설정 팝업."""

    def __init__(self, parent: QWidget | None, current: Path):
        super().__init__(parent)
        self.setWindowTitle("엑셀 저장 경로 설정")
        self.setModal(True)
        self.setFixedWidth(560)
        self.result_path: str | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        hint = QLabel("엑셀 파일이 저장될 기본 폴더입니다. 하위에 지역별 폴더가 자동 생성됩니다.")
        hint.setObjectName("MutedLabel")
        lay.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.path_edit = QLineEdit(str(current))
        browse_btn = QPushButton("찾아보기")
        browse_btn.clicked.connect(self.browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse_btn)
        lay.addLayout(row)

        btn_row = QHBoxLayout()
        default_btn = QPushButton("기본 경로")
        default_btn.clicked.connect(lambda: self.path_edit.setText(str(c.OUTPUT_ROOT)))
        save_btn = QPushButton("저장")
        save_btn.setObjectName("PrimaryBtn")
        save_btn.setDefault(True)
        cancel_btn = QPushButton("취소")
        save_btn.clicked.connect(self.submit)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(default_btn)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)

    def browse(self) -> None:
        cur = Path(self.path_edit.text().strip()) if self.path_edit.text().strip() else c.OUTPUT_ROOT
        picked = QFileDialog.getExistingDirectory(self, "엑셀 저장 폴더 선택", str(cur if cur.exists() else BASE_DIR))
        if picked:
            self.path_edit.setText(str(Path(picked)))

    def submit(self) -> None:
        raw = self.path_edit.text().strip()
        if not raw:
            QMessageBox.warning(self, "입력 확인", "저장 경로를 입력하세요.")
            return
        self.result_path = raw
        self.accept()


class LogWindow(QDialog):
    """실행 로그 비모달 팝업."""

    def __init__(self, parent: QWidget | None, lines: list[str], on_clear):
        super().__init__(parent)
        self.setWindowTitle("실행 로그")
        self.resize(780, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        self.text_box = QPlainTextEdit()
        self.text_box.setReadOnly(True)
        if lines:
            self.text_box.setPlainText("".join(lines).rstrip("\n"))
            self.text_box.verticalScrollBar().setValue(self.text_box.verticalScrollBar().maximum())
        lay.addWidget(self.text_box, 1)

        bar = QHBoxLayout()
        bar.addStretch()
        clear_btn = QPushButton("비우기")
        close_btn = QPushButton("닫기")
        clear_btn.clicked.connect(on_clear)
        close_btn.clicked.connect(self.close)
        bar.addWidget(clear_btn)
        bar.addWidget(close_btn)
        lay.addLayout(bar)

    def append_line(self, line: str) -> None:
        self.text_box.appendPlainText(line.rstrip("\n"))
        self.text_box.verticalScrollBar().setValue(self.text_box.verticalScrollBar().maximum())


class InlineLineEdit(QLineEdit):
    """인라인 편집용 입력칸: ↑=맨 앞, ↓=맨 끝, Enter=저장, Esc=취소."""

    def __init__(self, text: str, on_commit, on_cancel, parent: QWidget | None = None):
        super().__init__(text, parent)
        self._on_commit = on_commit
        self._on_cancel = on_cancel
        self.setStyleSheet(
            "QLineEdit { border: 1.5px solid #2563eb; border-radius: 4px; padding: 1px 5px; background: #ffffff; }"
        )

    def keyPressEvent(self, event) -> None:
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
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
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
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
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
        self.table.setHorizontalHeaderLabels(list(MANAGE_HEADERS))
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_context_menu)
        self.table.cellDoubleClicked.connect(self.on_cell_double_click)
        self.table.viewport().installEventFilter(self)
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, w in enumerate(COL_WIDTHS):
            self.table.setColumnWidth(col, w)
        lay.addWidget(self.table, 1)

        f2_sc = QShortcut(QKeySequence(Qt.Key.Key_F2), self.table)
        f2_sc.activated.connect(self.on_f2)

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

    def build_context_menu(self, row: int) -> QMenu:
        menu = QMenu(self.table)
        if 0 <= row < self.table.rowCount() and self._row_route_index(row) is not None:
            self.table.selectRow(row)
            self.table.setCurrentCell(row, 0)
            menu.addAction("노선 복사", self.copy_route_row)
            menu.addAction("노선 삭제", self.delete_route_row)
        else:
            menu.addAction("노선 추가", self.add_route_row)
        return menu

    def on_context_menu(self, pos: QPoint) -> None:
        row = self.table.rowAt(pos.y())
        if self.edit_state and row != self.edit_state["row"] and not self.commit_row_edit():
            return
        menu = self.build_context_menu(row)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def add_route_row(self) -> None:
        if self.edit_state and not self.commit_row_edit():
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        defaults = ["", "", "", "", "", "", "", "", "4", "Y", "FARE KRW", "사용"]
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
                w = InlineLineEdit(init[key], self.commit_row_edit, self.cancel_row_edit, self.table)
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


class App(QMainWindow):
    log_signal = Signal(str, object)
    login_done_signal = Signal()
    run_done_signal = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("세이버자동조회 (Sabre 실시간 운임)")
        self.resize(1120, 640)
        self.stop = threading.Event()
        self.routes = c.load_routes(ROUTES_PATH)
        self.session_cfg: dict | None = None
        self.log_lines: list[str] = []
        self.log_win: LogWindow | None = None
        self.manage_win: ManageWindow | None = None
        self.group_cards: dict[str, tuple[QFrame, QPushButton]] = {}
        self.job_entries: list[tuple[str, QCheckBox, dict, int]] = []

        self.log_signal.connect(self._on_log)
        self.login_done_signal.connect(lambda: self.login_btn.setEnabled(True))
        self.run_done_signal.connect(self.reset_buttons)

        self.build_menu()
        self.build_auto()
        self.refresh_jobs()

    def build_menu(self) -> None:
        mb = self.menuBar()
        self.file_menu = mb.addMenu("파일")
        self.quit_action = QAction("끝내기", self)
        self.quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        self.quit_action.triggered.connect(self.quit_app)
        self.file_menu.addAction(self.quit_action)

        self.settings_menu = mb.addMenu("설정")
        self.settings_menu.addAction("로그인 정보", self.open_login_settings)
        self.settings_menu.addAction("엑셀 저장 경로", self.open_output_dir_settings)
        self.settings_menu.addAction("조회 노선 관리", self.open_manage_window)

        self.help_menu = mb.addMenu("도움말")
        self.help_menu.addAction("사용 안내", self.show_help)

    def build_auto(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_lay = QVBoxLayout(central)
        root_lay.setContentsMargins(16, 14, 16, 12)
        root_lay.setSpacing(12)

        toolbar = QFrame()
        toolbar.setObjectName("SurfaceCard")
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(14, 10, 14, 10)
        tb_lay.setSpacing(10)

        start_lbl = QLabel("시작일")
        start_lbl.setObjectName("FieldLabel")
        self.start_edit = QLineEdit((date.today() + timedelta(3)).isoformat())
        self.start_edit.setFixedWidth(106)
        end_lbl = QLabel("종료일")
        end_lbl.setObjectName("FieldLabel")
        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("빈칸 = 노선 조회종료일")
        self.end_edit.setFixedWidth(158)

        self.login_btn = QPushButton("브라우저 실행/로그인")
        self.login_btn.clicked.connect(self.login)
        self.run_btn = QPushButton("▶ 조회 시작")
        self.run_btn.setObjectName("PrimaryBtn")
        self.run_btn.clicked.connect(self.start_run)
        self.stop_btn = QPushButton("■ 정지")
        self.stop_btn.setObjectName("DangerBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop.set)

        tb_lay.addWidget(start_lbl)
        tb_lay.addWidget(self.start_edit)
        tb_lay.addSpacing(4)
        tb_lay.addWidget(end_lbl)
        tb_lay.addWidget(self.end_edit)
        for label, months in (("한달", 1), ("분기", 3), ("반기", 6), ("일년", 12)):
            pbtn = QPushButton(label)
            pbtn.setObjectName("SmallBtn")
            pbtn.clicked.connect(lambda _chk=False, m=months: self.set_end_preset(m))
            tb_lay.addWidget(pbtn)
        tb_lay.addStretch()
        tb_lay.addWidget(self.login_btn)
        tb_lay.addWidget(self.run_btn)
        tb_lay.addWidget(self.stop_btn)
        root_lay.addWidget(toolbar)

        panel = QFrame()
        panel.setObjectName("PanelBox")
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(0, 0, 0, 0)
        panel_lay.setSpacing(0)

        head = QFrame()
        head.setObjectName("PanelHead")
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(14, 10, 14, 10)
        head_lay.setSpacing(8)
        title_lbl = QLabel("노선그룹/노선 선택")
        title_lbl.setObjectName("SectionTitle")
        self.main_search_edit = QLineEdit()
        self.main_search_edit.setPlaceholderText("노선그룹 · 공항 · 항공사 · 편명 검색")
        self.main_search_edit.setFixedWidth(260)
        self.main_search_edit.textChanged.connect(self.filter_job_cards)

        folder_btn = QPushButton("폴더열기")
        folder_btn.setObjectName("SmallBtn")
        folder_btn.clicked.connect(self.open_output_dir)
        all_on_btn = QPushButton("전체 선택")
        all_on_btn.setObjectName("SmallBtn")
        all_on_btn.clicked.connect(lambda: self.set_all_jobs(True))
        all_off_btn = QPushButton("선택 해제")
        all_off_btn.setObjectName("SmallBtn")
        all_off_btn.clicked.connect(lambda: self.set_all_jobs(False))

        head_lay.addWidget(title_lbl)
        head_lay.addSpacing(4)
        head_lay.addWidget(self.main_search_edit)
        head_lay.addStretch()
        head_lay.addWidget(folder_btn)
        head_lay.addWidget(all_on_btn)
        head_lay.addWidget(all_off_btn)
        panel_lay.addWidget(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.cards_host = QWidget()
        self.cards_host.setObjectName("CardsHost")
        self.cards_grid = QGridLayout(self.cards_host)
        self.cards_grid.setContentsMargins(14, 14, 14, 14)
        self.cards_grid.setSpacing(12)
        self.scroll.setWidget(self.cards_host)
        panel_lay.addWidget(self.scroll, 1)
        root_lay.addWidget(panel, 1)

        prog_row = QHBoxLayout()
        prog_row.setContentsMargins(0, 0, 0, 0)
        prog_row.setSpacing(8)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress_lbl = QLabel("0%")
        self.progress_lbl.setObjectName("MutedLabel")
        self.progress_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prog_row.addWidget(self.progress, 1)
        prog_row.addWidget(self.progress_lbl)
        root_lay.addLayout(prog_row)

        footer = QHBoxLayout()
        footer.setContentsMargins(2, 0, 2, 0)
        self.status_lbl = QLabel("대기 중")
        self.status_lbl.setObjectName("MutedLabel")
        log_btn = QPushButton("로그 보기")
        log_btn.setObjectName("SmallBtn")
        log_btn.clicked.connect(self.open_log_window)
        footer.addWidget(self.status_lbl, 1)
        footer.addWidget(log_btn)
        root_lay.addLayout(footer)

    def open_manage_window(self) -> None:
        if self.manage_win is not None and self.manage_win.isVisible():
            self.manage_win.showNormal()
            self.manage_win.raise_()
            self.manage_win.activateWindow()
            return
        self.manage_win = ManageWindow(self)
        self.manage_win.show()

    def open_login_settings(self) -> None:
        saved = read_config(CONFIG_PATH)
        if self.session_cfg:
            saved = {**saved, **self.session_cfg}
        dlg = LoginDialog(self, saved_cfg=saved, submit_label="저장")
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_data:
            return
        self.session_cfg = dlg.result_data
        if dlg.result_data["remember"]:
            save_login_config(dlg.result_data, CONFIG_PATH)
        else:
            clear_remembered_login(CONFIG_PATH)
        self.log("로그인 정보를 업데이트했습니다.")

    def open_output_dir_settings(self) -> None:
        dlg = OutputPathDialog(self, get_output_root())
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result_path is None:
            return
        save_output_root(dlg.result_path, CONFIG_PATH)
        self.log(f"엑셀 저장 경로 변경: {get_output_root()}")

    def open_output_dir(self) -> None:
        out_root = get_output_root()
        out_root.mkdir(parents=True, exist_ok=True)
        os.startfile(str(out_root))

    def set_end_preset(self, months: int) -> None:
        try:
            start = date.fromisoformat(self.start_edit.text().strip())
        except ValueError:
            QMessageBox.warning(self, "날짜 확인", "시작일을 YYYY-MM-DD 형식으로 먼저 입력하세요.")
            self.start_edit.setFocus()
            return
        self.end_edit.setText(add_months(start, months).isoformat())

    def show_help(self) -> None:
        QMessageBox.information(
            self,
            "도움말",
            "세이버자동조회 주요 조작\n\n"
            "• Ctrl+Q : 프로그램 끝내기\n"
            "• 설정 > 조회 노선 관리 : 노선 추가·수정·복사·삭제·검색·CSV\n"
            "• 노선 행 더블클릭 / F2 : 인라인 수정 (Enter 저장 / Esc 취소)\n"
            "• 텍스트 칸 ↑ / ↓ : 칸 내 맨 앞 / 맨 끝 커서 이동\n"
            "• 빈칸 우클릭 : 노선 추가  |  노선 행 우클릭 : 복사 / 삭제",
        )

    def quit_app(self) -> None:
        self.stop.set()
        if self.manage_win is not None:
            self.manage_win.close()
        if self.log_win is not None:
            self.log_win.close()
        self.close()

    def closeEvent(self, event) -> None:
        self.stop.set()
        if self.manage_win is not None and self.manage_win.isVisible():
            self.manage_win.close()
        if self.log_win is not None and self.log_win.isVisible():
            self.log_win.close()
        event.accept()

    def refresh_jobs(self) -> None:
        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.group_cards.clear()
        self.job_entries.clear()

        grouped = c.group_routes(self.routes)
        groups = list(grouped.keys())
        for col in range(3):
            self.cards_grid.setColumnStretch(col, 1)
        for idx, group in enumerate(groups):
            card = QFrame()
            card.setObjectName("RouteCard")
            card.setProperty("active", False)
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(12, 10, 12, 10)
            card_lay.setSpacing(6)

            hdr = QHBoxLayout()
            hdr.setSpacing(6)
            g_lbl = QLabel(group)
            g_lbl.setObjectName("CardTitle")
            tbtn = QPushButton("전체선택")
            tbtn.setObjectName("CardToggle")
            tbtn.setProperty("active", False)
            tbtn.clicked.connect(lambda _chk=False, g=group: self.toggle_group_jobs(g))
            hdr.addWidget(g_lbl)
            hdr.addWidget(tbtn)
            hdr.addStretch()
            card_lay.addLayout(hdr)

            for route in grouped[group]:
                for days in route["days"]:
                    ret = route["retFlight"]
                    if ret.startswith(route["airline"]):
                        ret = ret[len(route["airline"]):]
                    cb = QCheckBox(f"{route['depFlight']}/{ret} +{days}")
                    cb.stateChanged.connect(self.update_detail_states)
                    card_lay.addWidget(cb)
                    self.job_entries.append((group, cb, route, days))
            card_lay.addStretch()
            self.cards_grid.addWidget(card, idx // 3, idx % 3)
            self.group_cards[group] = (card, tbtn)
        self.filter_job_cards()

    def filter_job_cards(self) -> None:
        query = self.main_search_edit.text() if hasattr(self, "main_search_edit") else ""
        while self.cards_grid.count():
            self.cards_grid.takeAt(0)
        vis_idx = 0
        for group, (card, _btn) in self.group_cards.items():
            any_vis = False
            for g, cb, route, _days in self.job_entries:
                if g != group:
                    continue
                matched = matches_route_query(route, query)
                cb.setHidden(not matched)
                if matched:
                    any_vis = True
            card.setHidden(not any_vis)
            if any_vis:
                self.cards_grid.addWidget(card, vis_idx // 3, vis_idx % 3)
                vis_idx += 1
        for r in range((len(self.group_cards) + 2) // 3 + 1):
            self.cards_grid.setRowStretch(r, 0)
        self.cards_grid.setRowStretch((vis_idx + 2) // 3, 1)
        self.update_detail_states()

    def toggle_group_jobs(self, group: str) -> None:
        vals = [cb.isChecked() for g, cb, _, _ in self.job_entries if g == group and not cb.isHidden()]
        self.set_group_jobs(group, not any(vals))

    def set_group_jobs(self, group: str, selected: bool) -> None:
        for g, cb, _, _ in self.job_entries:
            if g == group and not cb.isHidden():
                cb.blockSignals(True)
                cb.setChecked(selected)
                cb.blockSignals(False)
        self.update_detail_states()

    def set_all_jobs(self, selected: bool) -> None:
        for _, cb, _, _ in self.job_entries:
            if not cb.isHidden():
                cb.blockSignals(True)
                cb.setChecked(selected)
                cb.blockSignals(False)
        self.update_detail_states()

    def selected_jobs(self) -> list[tuple[dict, int]]:
        return [(r, d) for _, cb, r, d in self.job_entries if cb.isChecked()]

    def update_detail_states(self) -> None:
        for group, (card, btn) in self.group_cards.items():
            active = any(cb.isChecked() for g, cb, _, _ in self.job_entries if g == group and not cb.isHidden())
            btn.setText("전체해제" if active else "전체선택")
            for widget in (card, btn):
                if widget.property("active") != active:
                    widget.setProperty("active", active)
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)

    def save_routes_and_refresh(self) -> None:
        c.save_routes(ROUTES_PATH, self.routes)
        if self.manage_win is not None and self.manage_win.isVisible():
            self.manage_win.refresh_table()
        self.refresh_jobs()

    def load_cfg(self) -> dict:
        cfg = read_config(CONFIG_PATH)
        if self.session_cfg:
            cfg = {**cfg, **self.session_cfg}
        cfg["_profile_dir"] = str(BASE_DIR / "output" / "chrome-sabre-profile")
        return cfg

    def login(self) -> None:
        saved = read_config(CONFIG_PATH)
        if not has_saved_login(saved):
            dlg = LoginDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_data:
                return
            self.session_cfg = dlg.result_data
            if dlg.result_data["remember"]:
                save_login_config(dlg.result_data, CONFIG_PATH)
            else:
                clear_remembered_login(CONFIG_PATH)
        cfg = self.load_cfg()
        self.stop.clear()
        self.login_btn.setEnabled(False)
        threading.Thread(target=self._login_worker, args=(cfg,), daemon=True).start()

    def _login_worker(self, cfg: dict) -> None:
        auth_failed = False

        def login_log(msg: str, progress=None) -> None:
            nonlocal auth_failed
            if "아이디/비밀번호 오류" in msg:
                auth_failed = True
            self.log(msg, progress)

        try:
            ok = t.launch_and_login(cfg, login_log, self.stop)
            if not ok and auth_failed:
                self.session_cfg = None
                clear_remembered_login(CONFIG_PATH)
                self.log("저장된 로그인 기억을 해제했습니다. 다시 [브라우저 실행/로그인]을 눌러 정보를 확인하세요.")
        finally:
            self.login_done_signal.emit()

    def start_run(self) -> None:
        jobs = self.selected_jobs()
        if not jobs:
            QMessageBox.information(self, "안내", "조회할 노선그룹 · 항공일수를 선택하세요.")
            return
        try:
            start = date.fromisoformat(self.start_edit.text().strip())
            end = date.fromisoformat(self.end_edit.text().strip()) if self.end_edit.text().strip() else None
        except ValueError:
            QMessageBox.critical(self, "날짜 오류", "날짜는 YYYY-MM-DD 형식으로 입력하세요.")
            return
        self.stop.clear()
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        threading.Thread(target=self.worker, args=(jobs, start, end), daemon=True).start()

    def worker(self, jobs, start: date, end_override) -> None:
        done, failed, today = [], [], date.today()
        grouped_done: dict[str, list[tuple[dict, int, Path]]] = {}
        cfg = self.load_cfg()
        planned = []
        for route, days in jobs:
            end = end_override or date.fromisoformat(route["endDate"])
            day_cnt = max(0, (end - start).days + 1)
            planned.append((route, days, end, day_cnt))
        total_days = max(1, sum(cnt for _, _, _, cnt in planned))
        done_days = 0
        self.log(f"전체 조회 시작: {len(planned)}개 항목 / 총 {total_days}일", (0, total_days))
        for route, days, end, day_cnt in planned:
            name = f"{c.route_region(route)} {route['airline']} +{days}"
            if end < start:
                failed.append(f"{name}: 종료일이 시작일보다 빠름")
                continue
            base_days = done_days

            def job_log(msg: str, progress=None, _base=base_days) -> None:
                if progress:
                    self.log(msg, (_base + progress[0], total_days))
                else:
                    self.log(msg)

            self.log(f"시작: {name} ({start} ~ {end})")
            try:
                path = t.run_job(route, days, start, end, today, job_log, self.stop, background=True, cfg=cfg)
            except (t.SessionExpired, RuntimeError) as exc:
                failed.append(f"{name}: {exc}")
                self.log(f"중단: {exc}")
                break
            except Exception as exc:
                failed.append(f"{name}: {exc}")
                self.log(f"실패: {name} {exc}")
                done_days += day_cnt
                continue
            done_days += day_cnt
            if path:
                done.append(str(path))
                grouped_done.setdefault(c.route_group(route), []).append((route, days, path))
                self.log(f"완료: {path}", (done_days, total_days))
            else:
                failed.append(f"{name}: 정지됨")
                break
        for grp, entries in grouped_done.items():
            if len(entries) >= 2:
                sum_path = c.group_summary_path(grp, c.route_region(entries[0][0]), today, root=cfg.get("outputRoot"))
                c.save_group_summary_workbook(sum_path, grp, entries)
                done.append(str(sum_path))
                self.log(f"그룹 최저가 통합 완료: {sum_path}")
        self.log("완료 파일\n" + ("\n".join(done) or "없음"))
        if failed:
            self.log("미완료\n" + "\n".join(failed))
        self.run_done_signal.emit()

    def reset_buttons(self) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def log(self, msg: str, progress=None) -> None:
        self.log_signal.emit(msg, progress)

    def _on_log(self, msg: str, progress=None) -> None:
        line = f"{datetime.now():%H:%M:%S} {msg}\n"
        self.log_lines.append(line)
        first = line.strip().splitlines()[0] if line.strip() else ""
        if first:
            self.status_lbl.setText(first)
        if self.log_win is not None and self.log_win.isVisible():
            self.log_win.append_line(line)
        if progress:
            cur, tot = progress
            tot = max(1, int(tot))
            cur = max(0, min(int(cur), tot))
            self.progress.setMaximum(tot)
            self.progress.setValue(cur)
            self.progress_lbl.setText(f"{cur}/{tot} ({int(cur * 100 / tot)}%)")

    def open_log_window(self) -> None:
        if self.log_win is not None and self.log_win.isVisible():
            self.log_win.showNormal()
            self.log_win.raise_()
            self.log_win.activateWindow()
            return
        self.log_win = LogWindow(self, self.log_lines, self._clear_logs)
        self.log_win.show()

    def _clear_logs(self) -> None:
        self.log_lines.clear()
        if self.log_win is not None and self.log_win.isVisible():
            self.log_win.text_box.clear()


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#2563eb"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    if hasattr(QPalette.ColorRole, "Accent"):
        pal.setColor(QPalette.ColorRole.Accent, QColor("#2563eb"))
    app.setPalette(pal)
    app.setStyleSheet(APP_QSS)


def main() -> None:
    app = QApplication(sys.argv)
    apply_theme(app)
    win = App()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
