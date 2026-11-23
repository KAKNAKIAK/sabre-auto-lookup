"""세이버자동조회 공통 UI 스타일, 설정 헬퍼, 팝업 대화상자."""
from __future__ import annotations

import calendar
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import sabre_core as c

BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
ROUTES_PATH = BASE_DIR / "sabre-routes.json"
CONFIG_PATH = BASE_DIR / "sabre-config.json"
BACKUP_DIR = BASE_DIR / "backups"


def get_asset_path(name: str) -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "assets" / name
        if bundled.exists():
            return bundled
    return BASE_DIR / "assets" / name


def load_app_icon() -> QIcon:
    for name in ("sabre_icon.ico", "sabre_icon.png"):
        p = get_asset_path(name)
        if p.exists():
            return QIcon(str(p))
    return QIcon()
CRED_KEYS = ("agentId", "password", "pcc")
FIELDS = (
    ("노선그룹", "routeGroup"),
    ("출발지", "origin"),
    ("도착지", "destination"),
    ("항공사", "airline"),
    ("출국편", "depFlight"),
    ("귀국편", "retFlight"),
    ("항공일수(+N)", "days"),
    ("조회시작일", "startDate"),
    ("조회종료일", "endDate"),
    ("조회인원", "pax"),
    ("조회클래스", "bookingClass"),
)
MANAGE_COLS = tuple(k for _, k in FIELDS) + ("fareOnly", "enabled")
MANAGE_HEADERS = tuple(lbl for lbl, _ in FIELDS) + ("운임만", "사용")
COL_WIDTHS = (150, 70, 70, 70, 100, 100, 110, 118, 118, 80, 88, 134, 80)
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
QPushButton#SuccessBtn {
    background-color: #16a34a;
    border-color: #16a34a;
    color: #ffffff;
}
QPushButton#SuccessBtn:hover {
    background-color: #15803d;
    border-color: #15803d;
}
QPushButton#SuccessBtn:disabled {
    background-color: #86efac;
    border-color: #86efac;
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
    selection-background-color: #fee2e2;
    selection-color: #991b1b;
    outline: 0;
}
QTableWidget::item:selected {
    background-color: #fee2e2;
    color: #991b1b;
    border: 1px solid #fca5a5;
}
QFrame#TableCard {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
}
QTableWidget#ManageTable {
    border: none;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}
QFrame#TableBlankZone {
    background-color: #ffffff;
    border: none;
    border-top: 1px dashed #e2e8f0;
    border-bottom-left-radius: 9px;
    border-bottom-right-radius: 9px;
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


def has_saved_output_root(cfg: dict | None = None, path: Path = CONFIG_PATH) -> bool:
    src = cfg if cfg is not None else read_config(path)
    return bool(str(src.get("outputRoot") or "").strip())


def validate_output_dir(folder: str | Path) -> tuple[bool, str]:
    """조회 시작 전 저장 폴더 생성 및 쓰기 가능 여부를 검사한다."""
    raw = str(folder or "").strip()
    if not raw:
        return False, "저장 경로가 비어 있습니다."
    target = Path(raw)
    probe = target / ".sabre_write_check.tmp"
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, ""
    except OSError as exc:
        return False, f"저장 경로에 접근하거나 파일을 쓸 수 없습니다.\n경로: {target}\n사유: {exc}"


def save_output_root(folder: str | Path, path: Path = CONFIG_PATH) -> None:
    cfg = read_config(path)
    raw = str(folder or "").strip()
    cfg["outputRoot"] = str(Path(raw)) if raw else str(c.OUTPUT_ROOT)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_backup_settings(cfg: dict | None = None, path: Path = CONFIG_PATH) -> dict:
    src = cfg if cfg is not None else read_config(path)
    return c.normalize_backup_cfg(src.get("routeBackup") if isinstance(src, dict) else None)


def save_backup_settings(settings: dict, path: Path = CONFIG_PATH) -> dict:
    normalized = c.normalize_backup_cfg(settings)
    cfg = read_config(path)
    cfg["routeBackup"] = normalized
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalized


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
    if key == "startDate":
        return c.route_start_date(route)
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


def toggle_window_maximize(win: QWidget) -> None:
    win.showNormal() if win.isMaximized() else win.showMaximized()


def bind_alt_enter(win: QWidget) -> None:
    for key in ("Alt+Return", "Alt+Enter"):
        sc = QShortcut(QKeySequence(key), win)
        sc.setContext(Qt.ShortcutContext.WindowShortcut)
        sc.activated.connect(lambda w=win: toggle_window_maximize(w))


def format_date_edit(edit: QLineEdit) -> str:
    fixed = c.normalize_date_text(edit.text())
    if fixed != edit.text():
        edit.setText(fixed)
    return fixed


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

    def __init__(self, parent: QWidget | None, current: Path, hint_text: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("엑셀 저장 경로 설정")
        self.setModal(True)
        self.setFixedWidth(560)
        self.result_path: str | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        hint = QLabel(hint_text or "엑셀 파일이 저장될 폴더입니다. 하위에 지역별 폴더가 자동 생성됩니다.")
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
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
        ok, err = validate_output_dir(raw)
        if not ok:
            QMessageBox.warning(self, "저장 경로 확인", err)
            return
        self.result_path = raw
        self.accept()


class LogWindow(QDialog):
    """실행 로그 비모달 팝업."""

    def __init__(self, parent: QWidget | None, lines: list[str], on_clear):
        super().__init__(parent)
        self.setWindowTitle("실행 로그")
        self.resize(780, 460)
        bind_alt_enter(self)
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


class SingleDateResultDialog(QDialog):
    """한날짜 조회 최저가 결과 팝업."""

    def __init__(self, parent: QWidget | None, title: str, body_text: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 480)
        bind_alt_enter(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        self.text_box = QPlainTextEdit()
        self.text_box.setReadOnly(True)
        self.text_box.setPlainText(body_text)
        lay.addWidget(self.text_box, 1)

        bar = QHBoxLayout()
        bar.addStretch()
        copy_best_btn = QPushButton("최저가 복사")
        copy_best_btn.setObjectName("PrimaryBtn")
        copy_all_btn = QPushButton("전체 복사")
        close_btn = QPushButton("닫기")
        copy_best_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.text_box.toPlainText().split("\n\n[그 외 조회 결과]")[0].split("\n\n[노선별 조회 결과]")[0]))
        copy_all_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.text_box.toPlainText()))
        close_btn.clicked.connect(self.close)
        bar.addWidget(copy_best_btn)
        bar.addWidget(copy_all_btn)
        bar.addWidget(close_btn)
        lay.addLayout(bar)


class EndDatePreviewDialog(QDialog):
    """최종 조회일 탐색 결과 미리보기 및 선택 적용 팝업."""

    def __init__(self, parent: QWidget | None, results: list[dict]):
        super().__init__(parent)
        self.setWindowTitle("최종 조회일 업데이트 미리보기")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.resize(840, 480)
        bind_alt_enter(self)
        self.selected_updates: dict[int, str] = {}
        self._rows: list[tuple[QCheckBox, dict]] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        changed_cnt = sum(1 for r in results if r["changed"])
        summary = QLabel(f"총 {len(results)}개 노선 탐색 완료 · 변경 감지 {changed_cnt}건 (체크된 항목만 저장됩니다)")
        summary.setObjectName("FieldLabel")
        lay.addWidget(summary)

        table = QTableWidget(len(results), 7)
        table.setHorizontalHeaderLabels(["적용", "노선그룹", "편명", "일수", "기존 종료일", "탐색 종료일", "상태"])
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(30)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, w in ((0, 52), (2, 115), (3, 70), (4, 110), (5, 110), (6, 140)):
            table.setColumnWidth(col, w)

        for r_idx, item in enumerate(results):
            route = item["route"]
            new_end = item["newEnd"]
            if not new_end:
                status = "탐색실패"
            elif item["isEarlierSeasonSplit"]:
                status = "시즌분할(확인필요)"
            elif item["changed"]:
                status = "변경"
            else:
                status = "유지"
            chk = QCheckBox()
            chk.setEnabled(bool(new_end))
            chk.setChecked(bool(item["changed"] and not item["isEarlierSeasonSplit"]))
            wrap = QWidget()
            wlay = QHBoxLayout(wrap)
            wlay.setContentsMargins(0, 0, 0, 0)
            wlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wlay.addWidget(chk)
            table.setCellWidget(r_idx, 0, wrap)
            self._rows.append((chk, item))

            vals = (
                c.route_group(route),
                c.flight_pair_label(route),
                ",".join(map(str, route["days"])),
                item["oldEnd"] or "-",
                new_end or "-",
                status,
            )
            for col, val in enumerate(vals, start=1):
                ti = QTableWidgetItem(val)
                ti.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(r_idx, col, ti)
        lay.addWidget(table, 1)

        bar = QHBoxLayout()
        bar.addStretch()
        apply_btn = QPushButton("선택 항목 적용")
        apply_btn.setObjectName("PrimaryBtn")
        apply_btn.setDefault(True)
        cancel_btn = QPushButton("취소")
        apply_btn.clicked.connect(self.apply_selected)
        cancel_btn.clicked.connect(self.reject)
        bar.addWidget(apply_btn)
        bar.addWidget(cancel_btn)
        lay.addLayout(bar)

    def apply_selected(self) -> None:
        self.selected_updates = {
            item["index"]: item["newEnd"]
            for chk, item in self._rows
            if chk.isChecked() and item["newEnd"]
        }
        self.accept()


class RouteBackupDialog(QDialog):
    """노선 DB 자동 백업 설정 및 시점 복원 팝업."""

    def __init__(
        self,
        parent: QWidget | None,
        routes_path: Path,
        backup_dir: Path,
        config_path: Path,
        on_restored=None,
    ):
        super().__init__(parent)
        self.routes_path = routes_path
        self.backup_dir = backup_dir
        self.config_path = config_path
        self.on_restored = on_restored
        self._items: list[dict] = []
        self.setWindowTitle("노선 백업 관리")
        self.setModal(True)
        self.resize(680, 500)
        bind_alt_enter(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(12)

        cfg_card = QFrame()
        cfg_card.setObjectName("SurfaceCard")
        cfg_lay = QVBoxLayout(cfg_card)
        cfg_lay.setContentsMargins(14, 12, 14, 12)
        cfg_lay.setSpacing(8)

        cur = get_backup_settings(path=self.config_path)
        self.enabled_chk = QCheckBox("노선 변경 시 자동 백업 사용")
        self.enabled_chk.setChecked(cur["enabled"])
        cfg_lay.addWidget(self.enabled_chk)

        opt_row = QHBoxLayout()
        opt_row.setSpacing(10)
        lbl_int = QLabel("백업 주기 (분)")
        lbl_int.setObjectName("FieldLabel")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(0, 1440)
        self.interval_spin.setValue(cur["intervalMinutes"])
        self.interval_spin.setFixedWidth(84)
        hint_int = QLabel("(0 = 변경 시마다 즉시)")
        hint_int.setObjectName("MutedLabel")

        lbl_keep = QLabel("보관 개수")
        lbl_keep.setObjectName("FieldLabel")
        self.keep_spin = QSpinBox()
        self.keep_spin.setRange(1, 200)
        self.keep_spin.setValue(cur["keepCount"])
        self.keep_spin.setFixedWidth(80)
        lbl_unit = QLabel("개")
        lbl_unit.setObjectName("MutedLabel")

        save_cfg_btn = QPushButton("설정 저장")
        save_cfg_btn.setObjectName("PrimaryBtn")
        save_cfg_btn.clicked.connect(self.save_settings)

        opt_row.addWidget(lbl_int)
        opt_row.addWidget(self.interval_spin)
        opt_row.addWidget(hint_int)
        opt_row.addSpacing(12)
        opt_row.addWidget(lbl_keep)
        opt_row.addWidget(self.keep_spin)
        opt_row.addWidget(lbl_unit)
        opt_row.addStretch()
        opt_row.addWidget(save_cfg_btn)
        cfg_lay.addLayout(opt_row)

        self.enabled_chk.toggled.connect(self._sync_enabled)
        self._sync_enabled(cur["enabled"])
        lay.addWidget(cfg_card)

        list_head = QHBoxLayout()
        title_lbl = QLabel("백업 목록 (최신순)")
        title_lbl.setObjectName("SectionTitle")
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("MutedLabel")
        now_btn = QPushButton("지금 백업")
        now_btn.setObjectName("SmallBtn")
        now_btn.clicked.connect(self.backup_now)
        folder_btn = QPushButton("백업 폴더 열기")
        folder_btn.setObjectName("SmallBtn")
        folder_btn.clicked.connect(self.open_backup_dir)
        list_head.addWidget(title_lbl)
        list_head.addSpacing(6)
        list_head.addWidget(self.count_lbl)
        list_head.addStretch()
        list_head.addWidget(now_btn)
        list_head.addWidget(folder_btn)
        lay.addLayout(list_head)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["백업 일시", "노선 수", "파일명"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)

        bar = QHBoxLayout()
        del_btn = QPushButton("선택 삭제")
        del_btn.clicked.connect(self.delete_selected)
        restore_btn = QPushButton("선택 시점으로 복원")
        restore_btn.setObjectName("PrimaryBtn")
        restore_btn.clicked.connect(self.restore_selected)
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        bar.addWidget(del_btn)
        bar.addStretch()
        bar.addWidget(restore_btn)
        bar.addWidget(close_btn)
        lay.addLayout(bar)

        self.refresh_list()

    def _sync_enabled(self, on: bool) -> None:
        self.interval_spin.setEnabled(on)
        self.keep_spin.setEnabled(on)

    def refresh_list(self) -> None:
        self._items = c.list_route_backups(self.backup_dir)
        self.table.setRowCount(len(self._items))
        for r, item in enumerate(self._items):
            vals = (item["savedAt"], f"{item['count']}개", item["name"])
            for col, val in enumerate(vals):
                ti = QTableWidgetItem(val)
                if col < 2:
                    ti.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, col, ti)
        self.count_lbl.setText(f"총 {len(self._items)}개")

    def save_settings(self) -> None:
        saved = save_backup_settings(
            {
                "enabled": self.enabled_chk.isChecked(),
                "intervalMinutes": self.interval_spin.value(),
                "keepCount": self.keep_spin.value(),
            },
            path=self.config_path,
        )
        c._prune_backups(self.backup_dir, saved["keepCount"])
        self.refresh_list()
        QMessageBox.information(
            self,
            "저장 완료",
            f"자동 백업 설정을 저장했습니다.\n"
            f"- 자동 백업: {'사용' if saved['enabled'] else '중지'}\n"
            f"- 주기: {'변경 시마다 즉시' if saved['intervalMinutes'] == 0 else str(saved['intervalMinutes']) + '분'}\n"
            f"- 최대 보관: {saved['keepCount']}개",
        )

    def backup_now(self) -> None:
        keep = self.keep_spin.value()
        created = c.create_route_backup(self.routes_path, self.backup_dir, keep_count=keep, force=True)
        self.refresh_list()
        if created:
            QMessageBox.information(self, "백업 완료", f"현재 노선 DB를 백업했습니다.\n{created.name}")
        else:
            QMessageBox.information(self, "안내", "백업할 노선 파일이 아직 없습니다.")

    def open_backup_dir(self) -> None:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(self.backup_dir))

    def _selected_item(self) -> dict | None:
        row = self.table.currentRow()
        return self._items[row] if 0 <= row < len(self._items) else None

    def delete_selected(self) -> None:
        item = self._selected_item()
        if not item:
            QMessageBox.information(self, "선택 확인", "삭제할 백업을 선택하세요.")
            return
        if QMessageBox.question(self, "백업 삭제", f"{item['savedAt']} 백업을 삭제할까요?") != QMessageBox.StandardButton.Yes:
            return
        item["path"].unlink(missing_ok=True)
        self.refresh_list()

    def restore_selected(self) -> None:
        item = self._selected_item()
        if not item:
            QMessageBox.information(self, "선택 확인", "복원할 백업을 선택하세요.")
            return
        ans = QMessageBox.question(
            self,
            "노선 백업 복원",
            f"{item['savedAt']} 백업({item['count']}개 노선)으로 복원할까요?\n"
            "현재 노선 상태도 복원 직전 자동으로 백업됩니다.",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            routes = c.restore_route_backup(item["path"], self.routes_path, self.backup_dir, keep_count=self.keep_spin.value())
        except Exception as exc:
            QMessageBox.critical(self, "복원 오류", str(exc))
            return
        if self.on_restored:
            self.on_restored(routes)
        self.refresh_list()
        QMessageBox.information(self, "복원 완료", f"{len(routes)}개 노선을 복원했습니다.")


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#2563eb"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    if hasattr(QPalette.ColorRole, "Accent"):
        pal.setColor(QPalette.ColorRole.Accent, QColor("#2563eb"))
    app.setPalette(pal)
    app.setStyleSheet(APP_QSS)
