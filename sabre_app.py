"""세이버자동조회 메인 화면 (PySide6 Qt6 + QSS)."""
from __future__ import annotations

import os
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

import sabre_core as c
import sabre_terminal as t
from sabre_manage import InlineComboBox, InlineLineEdit, ManageWindow
from sabre_ui import (
    APP_QSS, BASE_DIR, COL_WIDTHS, CONFIG_PATH, CRED_KEYS, ENABLED_CHOICES,
    FARE_CHOICES, FIELDS, MANAGE_COLS, MANAGE_HEADERS, ROUTES_PATH, SEARCH_KEYS,
    LoginDialog, LogWindow, OutputPathDialog, SingleDateResultDialog,
    add_months, apply_theme, bind_alt_enter, clear_remembered_login,
    format_date_edit, get_output_root, has_saved_login, mask_secret,
    matches_route_query, read_config, save_login_config, save_output_root,
    show, toggle_window_maximize,
)


class App(QMainWindow):
    log_signal = Signal(str, object)
    login_done_signal = Signal()
    run_done_signal = Signal()
    single_date_done_signal = Signal(str, str)

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
        self.single_result_win: SingleDateResultDialog | None = None
        self._end_autofilled = False
        self.group_cards: dict[str, tuple[QFrame, QPushButton]] = {}
        self.job_entries: list[tuple[str, QCheckBox, dict, int]] = []

        self.log_signal.connect(self._on_log)
        self.login_done_signal.connect(lambda: self.login_btn.setEnabled(True))
        self.run_done_signal.connect(self.reset_buttons)
        self.single_date_done_signal.connect(self._show_single_date_result)

        self.build_menu()
        self.build_auto()
        bind_alt_enter(self)
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

        self.start_lbl = QLabel("시작일")
        self.start_lbl.setObjectName("FieldLabel")
        self.start_edit = QLineEdit((date.today() + timedelta(3)).isoformat())
        self.start_edit.setFixedWidth(106)
        self.start_edit.editingFinished.connect(lambda: format_date_edit(self.start_edit))
        self.end_lbl = QLabel("종료일")
        self.end_lbl.setObjectName("FieldLabel")
        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("빈칸 = 노선 조회종료일")
        self.end_edit.setFixedWidth(158)
        self.end_edit.editingFinished.connect(lambda: format_date_edit(self.end_edit))

        self.login_btn = QPushButton("브라우저 실행/로그인")
        self.login_btn.clicked.connect(self.login)
        self.single_date_chk = QCheckBox("단건 일정 조회")
        self.single_date_chk.toggled.connect(self.on_single_date_toggle)
        self.run_btn = QPushButton("▶ 조회 시작")
        self.run_btn.setObjectName("PrimaryBtn")
        self.run_btn.clicked.connect(self.start_run)
        self.stop_btn = QPushButton("■ 정지")
        self.stop_btn.setObjectName("DangerBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop.set)

        tb_lay.addWidget(self.start_lbl)
        tb_lay.addWidget(self.start_edit)
        tb_lay.addSpacing(4)
        tb_lay.addWidget(self.end_lbl)
        tb_lay.addWidget(self.end_edit)
        self.preset_btns: list[QPushButton] = []
        for label, months in (("한달", 1), ("분기", 3), ("반기", 6), ("일년", 12)):
            pbtn = QPushButton(label)
            pbtn.setObjectName("SmallBtn")
            pbtn.clicked.connect(lambda _chk=False, m=months: self.set_end_preset(m))
            tb_lay.addWidget(pbtn)
            self.preset_btns.append(pbtn)
        self.single_pax_lbl = QLabel("인원")
        self.single_pax_lbl.setObjectName("FieldLabel")
        self.single_pax_edit = QLineEdit("1")
        self.single_pax_edit.setFixedWidth(48)
        self.single_pax_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.single_pax_lbl.setVisible(False)
        self.single_pax_edit.setVisible(False)
        tb_lay.addWidget(self.single_pax_lbl)
        tb_lay.addWidget(self.single_pax_edit)
        tb_lay.addStretch()
        tb_lay.addWidget(self.login_btn)
        tb_lay.addWidget(self.single_date_chk)
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
        self.all_toggle_btn = QPushButton("전체 선택")
        self.all_toggle_btn.setObjectName("SmallBtn")
        self.all_toggle_btn.clicked.connect(self.toggle_all_jobs)

        head_lay.addWidget(title_lbl)
        head_lay.addSpacing(4)
        head_lay.addWidget(self.main_search_edit)
        head_lay.addStretch()
        head_lay.addWidget(folder_btn)
        head_lay.addWidget(self.all_toggle_btn)
        panel_lay.addWidget(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.verticalScrollBar().setSingleStep(28)
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
        sorted_routes = sorted(self.routes, key=c.route_group, reverse=True)
        if sorted_routes != self.routes:
            self.routes = sorted_routes
            c.save_routes(ROUTES_PATH, self.routes)
            self.refresh_jobs()
        self.manage_win = ManageWindow(self)
        self.manage_win.show()

    def _apply_login_result(self, creds: dict) -> None:
        self.session_cfg = creds
        if creds["remember"]:
            save_login_config(creds, CONFIG_PATH)
        else:
            clear_remembered_login(CONFIG_PATH)

    def open_login_settings(self) -> None:
        saved = read_config(CONFIG_PATH)
        if self.session_cfg:
            saved = {**saved, **self.session_cfg}
        dlg = LoginDialog(self, saved_cfg=saved, submit_label="저장")
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_data:
            return
        self._apply_login_result(dlg.result_data)
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
            start = date.fromisoformat(format_date_edit(self.start_edit))
        except ValueError:
            QMessageBox.warning(self, "날짜 확인", "시작일을 YYYY-MM-DD 형식으로 먼저 입력하세요.")
            self.start_edit.setFocus()
            return
        self.end_edit.setText(add_months(start, months).isoformat())

    def on_single_date_toggle(self, checked: bool) -> None:
        if checked:
            self.start_lbl.setText("한국출발일")
            self.end_lbl.setText("한국도착일")
            self.end_edit.setPlaceholderText("YYYY-MM-DD")
            existing_end = format_date_edit(self.end_edit)
            if existing_end:
                self._end_autofilled = False
            else:
                self._end_autofilled = True
                try:
                    dep = date.fromisoformat(format_date_edit(self.start_edit))
                    self.end_edit.setText((dep + timedelta(3)).isoformat())
                except ValueError:
                    self.end_edit.setText(self.start_edit.text().strip())
            for btn in self.preset_btns:
                btn.setVisible(False)
            self.single_pax_lbl.setVisible(True)
            self.single_pax_edit.setVisible(True)
            self.run_btn.setText("▶ 최저가 확인")
            self.run_btn.setObjectName("SuccessBtn")
        else:
            self.start_lbl.setText("시작일")
            self.end_lbl.setText("종료일")
            self.end_edit.setPlaceholderText("빈칸 = 노선 조회종료일")
            if self._end_autofilled:
                self.end_edit.setText("")
                self._end_autofilled = False
            for btn in self.preset_btns:
                btn.setVisible(True)
            self.single_pax_lbl.setVisible(False)
            self.single_pax_edit.setVisible(False)
            self.run_btn.setText("▶ 조회 시작")
            self.run_btn.setObjectName("PrimaryBtn")
        self.run_btn.style().unpolish(self.run_btn)
        self.run_btn.style().polish(self.run_btn)
        self.filter_job_cards()

    def show_help(self) -> None:
        QMessageBox.information(
            self,
            "도움말",
            "세이버자동조회 주요 조작\n\n"
            "• Ctrl+Q : 프로그램 끝내기\n"
            "• Alt+Enter : 창 최대화 / 원래 크기 전환\n"
            "• 설정 > 조회 노선 관리 : 노선 추가·수정·복사·삭제·검색·CSV\n"
            "• 노선 행 더블클릭 / F2 : 인라인 수정 (Enter 저장 / Esc 취소)\n"
            "• 노선 관리 Ctrl+C / Ctrl+V : 셀 복사 / 붙여넣기 (여러 셀 일괄 붙여넣기)\n"
            "• 텍스트 칸 ↑ / ↓ : 칸 내 맨 앞 / 맨 끝 커서 이동\n"
            "• 빈칸 우클릭 : 노선 추가  |  노선 행 우클릭 : 복사 / 삭제",
        )

    def quit_app(self) -> None:
        self.stop.set()
        if self.manage_win is not None:
            self.manage_win.close()
        if self.log_win is not None:
            self.log_win.close()
        if self.single_result_win is not None:
            self.single_result_win.close()
        self.close()

    def closeEvent(self, event) -> None:
        self.stop.set()
        if self.manage_win is not None and self.manage_win.isVisible():
            self.manage_win.close()
        if self.log_win is not None and self.log_win.isVisible():
            self.log_win.close()
        if self.single_result_win is not None and self.single_result_win.isVisible():
            self.single_result_win.close()
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
        groups = sorted(grouped.keys(), reverse=True)
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
                    cb = QCheckBox(f"{c.flight_pair_label(route)} +{days}")
                    cb.stateChanged.connect(self.update_detail_states)
                    card_lay.addWidget(cb)
                    self.job_entries.append((group, cb, route, days))
            card_lay.addStretch()
            self.cards_grid.addWidget(card, idx // 3, idx % 3)
            self.group_cards[group] = (card, tbtn)
        self.filter_job_cards()

    def filter_job_cards(self) -> None:
        query = self.main_search_edit.text() if hasattr(self, "main_search_edit") else ""
        single_mode = hasattr(self, "single_date_chk") and self.single_date_chk.isChecked()
        while self.cards_grid.count():
            self.cards_grid.takeAt(0)
        vis_idx = 0
        for group, (card, _btn) in self.group_cards.items():
            any_vis = False
            seen_single: set[tuple] = set()
            for g, cb, route, days in self.job_entries:
                if g != group:
                    continue
                pair = c.flight_pair_label(route)
                cb.setText(pair if single_mode else f"{pair} +{days}")
                matched = matches_route_query(route, query)
                if matched and single_mode:
                    skey = (route["airline"], route["depFlight"], route["retFlight"],
                            c.route_pax(route), c.route_class(route), c.route_fare_only(route))
                    if skey in seen_single:
                        matched = False
                    else:
                        seen_single.add(skey)
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

    def toggle_all_jobs(self) -> None:
        any_checked = any(cb.isChecked() for _, cb, _, _ in self.job_entries if not cb.isHidden())
        self.set_all_jobs(not any_checked)

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
        any_vis_checked = any(cb.isChecked() for _, cb, _, _ in self.job_entries if not cb.isHidden())
        self.all_toggle_btn.setText("전체 해제" if any_vis_checked else "전체 선택")

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
            self._apply_login_result(dlg.result_data)
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
            start_txt = format_date_edit(self.start_edit)
            end_txt = format_date_edit(self.end_edit)
            start = date.fromisoformat(start_txt)
            end = date.fromisoformat(end_txt) if end_txt else None
        except ValueError:
            QMessageBox.critical(self, "날짜 오류", "날짜는 YYYY-MM-DD 형식으로 입력하세요.")
            return
        if self.single_date_chk.isChecked():
            if end is None:
                QMessageBox.warning(self, "날짜 확인", "한국도착일을 YYYY-MM-DD 형식으로 입력하세요.")
                self.end_edit.setFocus()
                return
            if end < start:
                QMessageBox.warning(self, "날짜 확인", f"한국도착일({end})이 한국출발일({start})보다 빠릅니다.")
                self.end_edit.setFocus()
                return
            pax_raw = self.single_pax_edit.text().strip()
            if not pax_raw.isdigit() or not (1 <= int(pax_raw) <= 9):
                QMessageBox.warning(self, "인원 확인", "조회 인원은 1~9 사이의 숫자로 입력하세요.")
                self.single_pax_edit.setFocus()
                return
            single_pax = int(pax_raw)
            # 한날짜 왕복 조회는 입력된 한국출발/도착일을 쓰므로 동일 편명의 중복 항공일수(+2/+3)는 1회만 조회한다.
            seen_routes: set[tuple] = set()
            planned = []
            span_days = (end - start).days
            for r, _d in jobs:
                key = (c.route_group(r), r["origin"], r["destination"], r["airline"],
                       r["depFlight"], r["retFlight"], c.route_class(r), c.route_fare_only(r))
                if key not in seen_routes:
                    seen_routes.add(key)
                    planned.append(({**r, "pax": single_pax}, span_days, start, end))
            self.stop.clear()
            self.run_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            threading.Thread(target=self.single_date_worker, args=(planned, start, end, single_pax), daemon=True).start()
            return
        planned, issues = c.plan_jobs(jobs, start, end)
        if issues and not planned:
            QMessageBox.warning(
                self,
                "조회 기간 확인",
                "조회 가능한 노선이 없습니다.\n\n" + "\n".join(issues),
            )
            return
        if issues:
            ans = QMessageBox.question(
                self,
                "조회 기간 확인",
                "아래 노선은 조회 기간 조건에 맞지 않아 제외됩니다.\n\n"
                + "\n".join(issues)
                + f"\n\n나머지 {len(planned)}개 항목만 조회를 진행할까요?",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.stop.clear()
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        threading.Thread(target=self.worker, args=(planned,), daemon=True).start()

    def single_date_worker(self, planned: list[tuple[dict, int, date, date]], dep_date: date, arr_date: date, pax: int = 1) -> None:
        cfg = self.load_cfg()
        self.log(f"단건 일정 조회 시작: {dep_date.isoformat()} ~ {arr_date.isoformat()} ({pax}명, {len(planned)}개 편명)", (0, max(1, len(planned))))
        try:
            records = t.run_single_date(planned, self.log, self.stop, background=True, cfg=cfg)
        except (t.SessionExpired, RuntimeError) as exc:
            self.log(f"중단: {exc}")
            self.single_date_done_signal.emit("단건 일정 조회 오류", f"조회 중단: {exc}")
            self.run_done_signal.emit()
            return
        except Exception as exc:
            self.log(f"실패: {exc}")
            self.single_date_done_signal.emit("단건 일정 조회 오류", f"조회 실패: {exc}")
            self.run_done_signal.emit()
            return
        if self.stop.is_set():
            self.log("단건 일정 조회 정지됨")
        elif records:
            body = c.build_single_date_popup_text(records, dep_date, arr_date)
            self.log(f"단건 일정 조회 완료 ({dep_date.isoformat()} ~ {arr_date.isoformat()}, {pax}명)")
            self.single_date_done_signal.emit(f"최저가 확인 ({dep_date.isoformat()} ~ {arr_date.isoformat()} · {pax}명)", body)
        self.run_done_signal.emit()

    def _show_single_date_result(self, title: str, body: str) -> None:
        if self.single_result_win is not None:
            self.single_result_win.close()
        self.single_result_win = SingleDateResultDialog(self, title, body)
        self.single_result_win.show()
        self.single_result_win.raise_()
        self.single_result_win.activateWindow()

    def worker(self, planned: list[tuple[dict, int, date, date]]) -> None:
        done, failed, today = [], [], date.today()
        grouped_done: dict[str, list[tuple[dict, int, Path]]] = {}
        cfg = self.load_cfg()
        total_days = max(1, sum((end - job_start).days + 1 for _, _, job_start, end in planned))
        done_days = 0
        self.log(f"전체 조회 시작: {len(planned)}개 항목 / 총 {total_days}일", (0, total_days))
        for route, days, job_start, end in planned:
            day_cnt = (end - job_start).days + 1
            name = f"{c.route_region(route)} {route['airline']} +{days}"
            base_days = done_days

            def job_log(msg: str, progress=None, _base=base_days) -> None:
                if progress:
                    self.log(msg, (_base + progress[0], total_days))
                else:
                    self.log(msg)

            self.log(f"시작: {name} ({job_start} ~ {end})")
            try:
                path = t.run_job(route, days, job_start, end, today, job_log, self.stop, background=True, cfg=cfg)
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
        for sum_path in c.save_group_summaries(grouped_done, today, root=cfg.get("outputRoot")):
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


def main() -> None:
    app = QApplication(sys.argv)
    apply_theme(app)
    win = App()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
