"""세이버자동조회 화면: 조회 노선 관리 + 자동조회."""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import sabre_core as c
import sabre_terminal as t

BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
ROUTES_PATH = BASE_DIR / "sabre-routes.json"
CONFIG_PATH = BASE_DIR / "sabre-config.json"
CRED_KEYS = ("agentId", "password", "pcc")
FIELDS = (("노선그룹", "routeGroup"), ("출발지", "origin"), ("도착지", "destination"),
          ("항공사", "airline"), ("출국편", "depFlight"), ("귀국편", "retFlight"),
          ("항공일수(+N)", "days"), ("조회종료일", "endDate"), ("조회인원", "pax"), ("조회클래스", "bookingClass"))
MANAGE_COLS = tuple(k for _, k in FIELDS) + ("fareOnly", "enabled")
SEARCH_KEYS = ("routeGroup", "origin", "destination", "airline", "depFlight", "retFlight")
FARE_CHOICES = ("FARE KRW", "TOTAL KRW")
ENABLED_CHOICES = ("사용", "중지")


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


def save_login_config(creds: dict, path: Path = CONFIG_PATH) -> None:
    data = {
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


class LoginDialog(tk.Toplevel):
    """Sabre 로그인 정보 입력 팝업 (로그인 정보 기억하기 포함)."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.title("Sabre 로그인")
        self.resizable(False, False)
        self.transient(parent)
        self.result: dict | None = None

        body = ttk.Frame(self, padding=14)
        body.pack(fill=tk.BOTH, expand=True)

        self.agent_var = tk.StringVar()
        self.pw_var = tk.StringVar()
        self.pcc_var = tk.StringVar()
        self.remember_var = tk.BooleanVar(value=True)

        ttk.Label(body, text="Agent ID").grid(row=0, column=0, sticky="w", pady=4)
        self.agent_entry = ttk.Entry(body, textvariable=self.agent_var, width=26)
        self.agent_entry.grid(row=0, column=1, padx=(10, 0), pady=4)

        ttk.Label(body, text="Password").grid(row=1, column=0, sticky="w", pady=4)
        self.pw_entry = ttk.Entry(body, textvariable=self.pw_var, width=26, show="*")
        self.pw_entry.grid(row=1, column=1, padx=(10, 0), pady=4)

        ttk.Label(body, text="PCC").grid(row=2, column=0, sticky="w", pady=4)
        self.pcc_entry = ttk.Entry(body, textvariable=self.pcc_var, width=26)
        self.pcc_entry.grid(row=2, column=1, padx=(10, 0), pady=4)

        ttk.Checkbutton(body, text="로그인 정보 기억하기", variable=self.remember_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 10)
        )

        btns = ttk.Frame(body)
        btns.grid(row=4, column=0, columnspan=2, sticky="e")
        ttk.Button(btns, text="로그인", width=10, command=self.submit).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="취소", width=8, command=self.cancel).pack(side=tk.LEFT)

        self.bind("<Return>", lambda _e: self.submit())
        self.bind("<Escape>", lambda _e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        dw, dh = self.winfo_reqwidth(), self.winfo_reqheight()
        if pw > 1 and ph > 1:
            self.geometry(f"+{px + max(0, (pw - dw) // 2)}+{py + max(0, (ph - dh) // 2)}")
        self.grab_set()
        self.agent_entry.focus_set()

    def submit(self) -> None:
        agent_id = self.agent_var.get().strip()
        password = self.pw_var.get()
        pcc = self.pcc_var.get().strip().upper()
        if not agent_id:
            messagebox.showwarning("입력 확인", "Agent ID를 입력하세요.", parent=self)
            self.agent_entry.focus_set()
            return
        if not password:
            messagebox.showwarning("입력 확인", "Password를 입력하세요.", parent=self)
            self.pw_entry.focus_set()
            return
        if not pcc:
            messagebox.showwarning("입력 확인", "PCC를 입력하세요.", parent=self)
            self.pcc_entry.focus_set()
            return
        self.result = {
            "agentId": agent_id,
            "password": password,
            "pcc": pcc,
            "remember": bool(self.remember_var.get()),
        }
        self.destroy()

    def cancel(self) -> None:
        self.result = None
        self.destroy()


def show(route: dict, key: str) -> str:
    if key == "routeGroup":
        return c.route_group(route)
    if key == "pax":
        return str(c.route_pax(route))
    if key == "bookingClass":
        return c.route_class(route)
    return ", ".join(map(str, route[key])) if key == "days" else str(route[key])


def matches_route_query(route: dict, query: str) -> bool:
    """노선그룹~귀국편(및 지역명) 범위에서 공백 구분 다중 키워드를 유연하게 검색한다."""
    tokens = query.strip().upper().split()
    if not tokens:
        return True
    hay = " ".join([show(route, k) for k in SEARCH_KEYS] + [c.route_region(route)]).upper()
    compact = re.sub(r"[\s-]+", "", hay)
    return all(tok in hay or re.sub(r"[\s-]+", "", tok) in compact for tok in tokens)


class App:
    def __init__(self, root: tk.Tk):
        self.root, self.stop, self.events = root, threading.Event(), queue.Queue()
        root.title("세이버자동조회 (Sabre 실시간 운임)")
        root.geometry("1120x620")
        self.routes = c.load_routes(ROUTES_PATH)
        self.group_toggle_vars: dict[str, tk.StringVar] = {}
        self.job_entries: list[tuple[str, tk.BooleanVar, ttk.Checkbutton, dict, int]] = []
        self.detail_summary_var = tk.StringVar(value="선택 0개 노선그룹 / 0개 항목")
        self.status_var = tk.StringVar(value="대기 중")
        self.log_lines: list[str] = []
        self.log_win: tk.Toplevel | None = None
        self.log_box: tk.Text | None = None
        self.session_cfg: dict | None = None
        self.edit_state: dict | None = None
        self.manage_search_var = tk.StringVar()
        self.manage_count_var = tk.StringVar()
        nb = ttk.Notebook(root)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        auto, manage = ttk.Frame(nb, padding=8), ttk.Frame(nb, padding=8)
        nb.add(auto, text="자동조회")
        nb.add(manage, text="조회 노선 관리")
        nb.bind("<<NotebookTabChanged>>", lambda _e: self.commit_row_edit() if self.edit_state else None)
        self.build_auto(auto)
        self.build_manage(manage)
        root.after(200, self.pump)

    # ----- 자동조회 -----
    def build_auto(self, tab: ttk.Frame) -> None:
        top = ttk.Frame(tab)
        top.pack(fill=tk.X)
        self.start_var = tk.StringVar(value=(date.today() + timedelta(1)).isoformat())
        self.end_var = tk.StringVar()
        ttk.Label(top, text="시작일").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.start_var, width=12).pack(side=tk.LEFT, padx=4)
        ttk.Label(top, text="종료일 (빈칸 = 노선 조회종료일)").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.end_var, width=12).pack(side=tk.LEFT, padx=4)
        self.stop_btn = ttk.Button(top, text="■ 정지", command=self.stop.set, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.RIGHT)
        self.run_btn = ttk.Button(top, text="▶ 조회 시작", command=self.start_run)
        self.run_btn.pack(side=tk.RIGHT, padx=4)
        self.login_btn = ttk.Button(top, text="브라우저 실행/로그인", command=self.login)
        self.login_btn.pack(side=tk.RIGHT, padx=4)

        # 노선그룹별 항공사 · 편명 · 항공일수 선택 카드
        det_box = ttk.LabelFrame(tab, text="항공사 · 편명 · 항공일수 선택", padding=(8, 6))
        det_box.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        det_bar = ttk.Frame(det_box)
        det_bar.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(det_bar, textvariable=self.detail_summary_var).pack(side=tk.LEFT)
        ttk.Button(det_bar, text="선택 해제", command=lambda: self.set_all_jobs(False)).pack(side=tk.RIGHT)
        ttk.Button(det_bar, text="전체 선택", command=lambda: self.set_all_jobs(True)).pack(side=tk.RIGHT, padx=4)
        ttk.Button(det_bar, text="엑셀 폴더 열기", command=self.open_output_dir).pack(side=tk.RIGHT, padx=4)
        self.detail_container = ttk.Frame(det_box)
        self.detail_container.pack(fill=tk.BOTH, expand=True)
        self.jobs_canvas = tk.Canvas(self.detail_container, height=200, highlightthickness=0)
        scroll = ttk.Scrollbar(self.detail_container, orient=tk.VERTICAL, command=self.jobs_canvas.yview)
        self.jobs_frame = ttk.Frame(self.jobs_canvas)
        self.jobs_frame.bind("<Configure>", lambda _e: self.jobs_canvas.configure(scrollregion=self.jobs_canvas.bbox("all")))
        win = self.jobs_canvas.create_window((0, 0), window=self.jobs_frame, anchor="nw")
        self.jobs_canvas.bind("<Configure>", lambda e: self.jobs_canvas.itemconfig(win, width=e.width))
        self.jobs_canvas.configure(yscrollcommand=scroll.set)
        self.jobs_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.progress = ttk.Progressbar(tab, maximum=1)
        self.progress.pack(fill=tk.X, pady=(8, 0))
        footer = ttk.Frame(tab)
        footer.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(footer, textvariable=self.status_var).pack(side=tk.LEFT)
        ttk.Button(footer, text="로그 보기", command=self.open_log_window).pack(side=tk.RIGHT)
        self.refresh_jobs()

    def open_output_dir(self) -> None:
        c.OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        os.startfile(str(c.OUTPUT_ROOT))

    def toggle_group_jobs(self, group: str) -> None:
        vals = [v.get() for g, v, _, _, _ in self.job_entries if g == group]
        self.set_group_jobs(group, not any(vals))

    def set_group_jobs(self, group: str, selected: bool) -> None:
        for g, var, _, _, _ in self.job_entries:
            if g == group:
                var.set(selected)
        self.update_detail_states()

    def set_all_jobs(self, selected: bool) -> None:
        for _, var, _, _, _ in self.job_entries:
            var.set(selected)
        self.update_detail_states()

    def update_detail_states(self) -> None:
        for group, tvar in self.group_toggle_vars.items():
            vals = [v.get() for g, v, _, _, _ in self.job_entries if g == group]
            tvar.set("전체해제" if any(vals) else "전체선택")
        sel = self.selected_jobs()
        grp_cnt = len({show(r, "routeGroup") for r, _ in sel})
        self.detail_summary_var.set(f"선택 {grp_cnt}개 노선그룹 / {len(sel)}개 조회항목")

    def selected_jobs(self) -> list[tuple[dict, int]]:
        return [(r, d) for _, var, _, r, d in self.job_entries if var.get()]

    def refresh_jobs(self) -> None:
        for w in self.jobs_frame.winfo_children():
            w.destroy()
        self.group_toggle_vars.clear()
        self.job_entries.clear()
        grouped = c.group_routes(self.routes)
        groups = list(grouped.keys())
        for col in range(3):
            self.jobs_frame.columnconfigure(col, weight=1, uniform="sabre_group")
        for idx, group in enumerate(groups):
            hdr = ttk.Frame(self.jobs_frame)
            ttk.Label(hdr, text=group).pack(side=tk.LEFT)
            tvar = tk.StringVar(value="전체선택")
            self.group_toggle_vars[group] = tvar
            ttk.Button(hdr, textvariable=tvar, width=8, command=lambda g=group: self.toggle_group_jobs(g)).pack(side=tk.LEFT, padx=(6, 0))
            card = ttk.LabelFrame(self.jobs_frame, labelwidget=hdr, padding=(6, 4))
            card.grid(row=idx // 3, column=idx % 3, padx=(0, 6), pady=(0, 6), sticky="nsew")
            for route in grouped[group]:
                for days in route["days"]:
                    var = tk.BooleanVar(value=False)
                    ret = route["retFlight"]
                    if ret.startswith(route["airline"]):
                        ret = ret[len(route["airline"]):]
                    lbl = f"{route['depFlight']}/{ret} +{days}"
                    cb = ttk.Checkbutton(card, text=lbl, variable=var,
                                         command=self.update_detail_states)
                    cb.pack(anchor="w")
                    self.job_entries.append((group, var, cb, route, days))
        self.update_detail_states()

    def load_cfg(self) -> dict:
        cfg = read_config(CONFIG_PATH)
        if self.session_cfg:
            cfg = {**cfg, **self.session_cfg}
        cfg["_profile_dir"] = str(BASE_DIR / "output" / "chrome-sabre-profile")
        return cfg

    def login(self) -> None:
        saved = read_config(CONFIG_PATH)
        if not has_saved_login(saved):
            dlg = LoginDialog(self.root)
            self.root.wait_window(dlg)
            if not dlg.result:
                return
            self.session_cfg = dlg.result
            if dlg.result["remember"]:
                save_login_config(dlg.result, CONFIG_PATH)
            else:
                clear_remembered_login(CONFIG_PATH)
        cfg = self.load_cfg()
        self.stop.clear()
        self.login_btn.configure(state=tk.DISABLED)
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
            try:
                self.root.after(0, lambda: self.login_btn.configure(state=tk.NORMAL))
            except (tk.TclError, RuntimeError):
                pass

    def start_run(self) -> None:
        jobs = self.selected_jobs()
        if not jobs:
            messagebox.showinfo("안내", "조회할 노선그룹 · 항공일수를 선택하세요.")
            return
        try:
            start = date.fromisoformat(self.start_var.get().strip())
            end = date.fromisoformat(self.end_var.get().strip()) if self.end_var.get().strip() else None
        except ValueError:
            messagebox.showerror("날짜 오류", "날짜는 YYYY-MM-DD 형식으로 입력하세요.")
            return
        self.stop.clear()
        self.run_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        threading.Thread(target=self.worker, args=(jobs, start, end), daemon=True).start()

    def worker(self, jobs, start: date, end_override) -> None:
        done, failed, today = [], [], date.today()
        cfg = self.load_cfg()
        for route, days in jobs:
            name = f"{c.route_region(route)} {route['airline']} +{days}"
            end = end_override or date.fromisoformat(route["endDate"])
            if end < start:
                failed.append(f"{name}: 종료일이 시작일보다 빠름")
                continue
            self.log(f"시작: {name} ({start} ~ {end})")
            try:
                path = t.run_job(route, days, start, end, today, self.log, self.stop,
                                 background=True, cfg=cfg)
            except (t.SessionExpired, RuntimeError) as exc:
                failed.append(f"{name}: {exc}")
                self.log(f"중단: {exc}")
                break  # 세션/작업창 문제는 다음 노선도 같은 이유로 실패
            except Exception as exc:
                failed.append(f"{name}: {exc}")
                self.log(f"실패: {name} {exc}")
                continue
            if path:
                done.append(str(path))
                self.log(f"완료: {path}")
            else:
                failed.append(f"{name}: 정지됨")
                break
        self.log("완료 파일\n" + ("\n".join(done) or "없음"))
        if failed:
            self.log("미완료\n" + "\n".join(failed))
        self.root.after(0, self.reset_buttons)

    def reset_buttons(self) -> None:
        self.run_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)

    def log(self, msg: str, progress=None) -> None:
        self.events.put((msg, progress))

    def open_log_window(self) -> None:
        if self.log_win is not None and self.log_win.winfo_exists():
            self.log_win.deiconify()
            self.log_win.lift()
            self.log_win.focus_set()
            return
        win = tk.Toplevel(self.root)
        win.title("실행 로그")
        win.geometry("760x440")
        body = ttk.Frame(win, padding=8)
        body.pack(fill=tk.BOTH, expand=True)
        box = tk.Text(body, wrap=tk.WORD)
        scroll = ttk.Scrollbar(body, orient=tk.VERTICAL, command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        if self.log_lines:
            box.insert(tk.END, "".join(self.log_lines))
            box.see(tk.END)
        bar = ttk.Frame(win, padding=(8, 0, 8, 8))
        bar.pack(fill=tk.X)
        ttk.Button(bar, text="닫기", width=8, command=lambda: self._close_log_window()).pack(side=tk.RIGHT)
        ttk.Button(bar, text="비우기", width=8, command=self._clear_logs).pack(side=tk.RIGHT, padx=(0, 6))
        win.protocol("WM_DELETE_WINDOW", self._close_log_window)
        self.log_win, self.log_box = win, box

    def _clear_logs(self) -> None:
        self.log_lines.clear()
        if self._log_open():
            self.log_box.delete("1.0", tk.END)

    def _close_log_window(self) -> None:
        win = self.log_win
        self.log_win, self.log_box = None, None
        if win is not None and win.winfo_exists():
            win.destroy()

    def _log_open(self) -> bool:
        return self.log_box is not None and self.log_win is not None and self.log_win.winfo_exists()

    def pump(self) -> None:
        while not self.events.empty():
            msg, progress = self.events.get()
            line = f"{datetime.now():%H:%M:%S} {msg}\n"
            self.log_lines.append(line)
            first = line.strip().splitlines()[0] if line.strip() else ""
            if first:
                self.status_var.set(first)
            if self._log_open():
                self.log_box.insert(tk.END, line)
                self.log_box.see(tk.END)
            if progress:
                self.progress.configure(maximum=progress[1], value=progress[0])
        self.root.after(200, self.pump)

    # ----- 조회 노선 관리 -----
    def build_manage(self, tab: ttk.Frame) -> None:
        search_bar = ttk.Frame(tab)
        search_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(search_bar, text="노선 검색").pack(side=tk.LEFT)
        search_entry = ttk.Entry(search_bar, textvariable=self.manage_search_var, width=34)
        search_entry.pack(side=tk.LEFT, padx=(6, 4))
        ttk.Label(search_bar, textvariable=self.manage_count_var).pack(side=tk.RIGHT)
        self.manage_search_var.trace_add("write", lambda *_a: self.refresh_tree())
        tree_wrap = ttk.Frame(tab)
        tree_wrap.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tree_wrap, columns=MANAGE_COLS, show="headings", height=16)
        yscroll = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self._on_tree_scroll)
        self.tree.configure(yscrollcommand=yscroll.set)
        col_widths = {"routeGroup": 95, "origin": 55, "destination": 55, "airline": 55, "depFlight": 75,
                      "retFlight": 75, "days": 85, "endDate": 95, "pax": 65, "bookingClass": 75,
                      "fareOnly": 95, "enabled": 60}
        for label, key in FIELDS + (("운임만", "fareOnly"), ("사용", "enabled")):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=col_widths.get(key, 85), anchor="center")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        self.tree.bind("<F2>", self.on_tree_f2)
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Button-3>", self.on_tree_right_click)
        self.tree.bind("<Configure>", lambda _e: self._reposition_row_editors())
        btns = ttk.Frame(tab)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btns, text="CSV 내보내기", command=self.export_csv).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btns, text="CSV 불러오기", command=self.import_csv).pack(side=tk.LEFT)
        ttk.Button(btns, text="목록 새로고침", command=self.reload_routes).pack(side=tk.RIGHT)
        self.refresh_tree()

    def _on_tree_scroll(self, *args) -> None:
        self.tree.yview(*args)
        self._reposition_row_editors()

    def reload_routes(self) -> None:
        self.cancel_row_edit()
        self.routes = c.load_routes(ROUTES_PATH)
        self.refresh_tree()
        self.refresh_jobs()

    def refresh_tree(self) -> None:
        self.cancel_row_edit()
        self.tree.delete(*self.tree.get_children())
        query = self.manage_search_var.get()
        shown = 0
        for i, r in enumerate(self.routes):
            if not matches_route_query(r, query):
                continue
            values = [
                ("최저가" if k == "bookingClass" and not show(r, k) else show(r, k))
                for _, k in FIELDS
            ] + ["FARE KRW" if c.route_fare_only(r) else "TOTAL KRW", "사용" if r.get("enabled", True) else "중지"]
            self.tree.insert("", tk.END, iid=str(i), values=values)
            shown += 1
        total = len(self.routes)
        self.manage_count_var.set(f"검색 {shown} / {total}개" if query.strip() else f"총 {total}개")

    def on_tree_click(self, event) -> None:
        if not self.edit_state:
            return
        iid = self.tree.identify_row(event.y)
        if iid != self.edit_state["iid"]:
            self.commit_row_edit()

    def _build_tree_menu(self, iid: str) -> tk.Menu:
        menu = tk.Menu(self.tree, tearoff=False)
        if iid and iid.isdigit() and self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            menu.add_command(label="노선 복사", command=self.copy_route_row)
            menu.add_command(label="노선 삭제", command=self.delete)
        else:
            menu.add_command(label="노선 추가", command=self.add_route_row)
        return menu

    def on_tree_right_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if self.edit_state and iid != self.edit_state["iid"] and not self.commit_row_edit():
            return
        menu = self._build_tree_menu(iid)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def on_tree_double_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        col_id = self.tree.identify_column(event.x)
        col_idx = int(col_id[1:]) - 1 if col_id.startswith("#") and col_id[1:].isdigit() else 0
        focus_col = MANAGE_COLS[col_idx] if 0 <= col_idx < len(MANAGE_COLS) else MANAGE_COLS[0]
        self.start_row_edit(iid, focus_col=focus_col)

    def on_tree_f2(self, _event=None) -> str:
        sel = self.tree.selection()
        iid = sel[0] if sel else self.tree.focus()
        if iid and self.tree.exists(iid):
            self.start_row_edit(iid, focus_col=MANAGE_COLS[0])
        return "break"

    def add_route_row(self) -> None:
        if self.edit_state and not self.commit_row_edit():
            return
        iid = "new"
        if self.tree.exists(iid):
            self.tree.delete(iid)
        defaults = ["", "", "", "", "", "", "", "", "4", "Y", "FARE KRW", "사용"]
        self.tree.insert("", tk.END, iid=iid, values=defaults)
        self.tree.selection_set(iid)
        self.tree.see(iid)
        self.start_row_edit(iid, focus_col="routeGroup")

    def start_row_edit(self, iid: str, focus_col: str = "routeGroup") -> None:
        if self.edit_state:
            if self.edit_state["iid"] == iid:
                w = self.edit_state["widgets"].get(focus_col)
                if w is not None:
                    w.focus_set()
                return
            if not self.commit_row_edit():
                return
        if not self.tree.exists(iid):
            return
        index = int(iid) if iid.isdigit() else None
        if index is not None:
            route = self.routes[index]
            init = {k: show(route, k) for _, k in FIELDS}
            init["fareOnly"] = "FARE KRW" if c.route_fare_only(route) else "TOTAL KRW"
            init["enabled"] = "사용" if route.get("enabled", True) else "중지"
        else:
            init = {k: ("4" if k == "pax" else "Y" if k == "bookingClass" else "") for _, k in FIELDS}
            init["fareOnly"] = "FARE KRW"
            init["enabled"] = "사용"

        self.tree.see(iid)
        self.tree.update_idletasks()
        vars_map: dict[str, tk.StringVar] = {}
        widgets: dict[str, tk.Widget] = {}
        for col in MANAGE_COLS:
            var = tk.StringVar(value=init[col])
            vars_map[col] = var
            if col == "fareOnly":
                w = ttk.Combobox(self.tree, textvariable=var, values=FARE_CHOICES, state="readonly")
            elif col == "enabled":
                w = ttk.Combobox(self.tree, textvariable=var, values=ENABLED_CHOICES, state="readonly")
            else:
                w = ttk.Entry(self.tree, textvariable=var)
                w.bind("<Down>", lambda _e, entry=w: self._move_entry_cursor(entry, tk.END))
                w.bind("<Up>", lambda _e, entry=w: self._move_entry_cursor(entry, 0))
            w.bind("<Return>", lambda _e: self.commit_row_edit())
            w.bind("<Escape>", lambda _e: self.cancel_row_edit())
            widgets[col] = w
        self.edit_state = {"iid": iid, "index": index, "vars": vars_map, "widgets": widgets}
        self._reposition_row_editors()
        target = widgets.get(focus_col) or widgets[MANAGE_COLS[0]]
        target.focus_set()
        if isinstance(target, ttk.Entry):
            target.selection_range(0, tk.END)

    @staticmethod
    def _move_entry_cursor(entry: ttk.Entry, pos: int | str) -> str:
        entry.selection_clear()
        entry.icursor(pos)
        return "break"

    def _reposition_row_editors(self) -> None:
        if not self.edit_state:
            return
        iid = self.edit_state["iid"]
        if not self.tree.exists(iid):
            self.cancel_row_edit()
            return
        for col, w in self.edit_state["widgets"].items():
            bbox = self.tree.bbox(iid, col)
            if bbox:
                x, y, width, height = bbox
                w.place(x=x, y=y, width=width, height=height)
            else:
                w.place_forget()

    def cancel_row_edit(self) -> None:
        state = self.edit_state
        if not state:
            return
        self.edit_state = None
        for w in state["widgets"].values():
            try:
                w.destroy()
            except tk.TclError:
                pass
        if state["index"] is None and self.tree.exists(state["iid"]):
            self.tree.delete(state["iid"])

    def commit_row_edit(self) -> bool:
        state = self.edit_state
        if not state:
            return True
        raw = {k: state["vars"][k].get() for _, k in FIELDS}
        index = state["index"]
        if index is None and not any(
            raw.get(k, "").strip() for _, k in FIELDS if k not in ("pax", "bookingClass")
        ):
            messagebox.showwarning(
                "미저장 안내",
                "아직 저장되지 않았습니다.\n입력 없이 나가면 추가한 빈 노선 행이 삭제됩니다.",
            )
            self.cancel_row_edit()
            return True
        if index is not None:
            prev = self.routes[index]
            if prev.get("destination", "").upper() == raw.get("destination", "").strip().upper() and prev.get("region"):
                raw["region"] = prev["region"]
        fare_only = state["vars"]["fareOnly"].get() != "TOTAL KRW"
        enabled = state["vars"]["enabled"].get() != "중지"
        try:
            route = c.normalize_route({**raw, "fareOnly": fare_only, "enabled": enabled}, allow_partial=True)
        except ValueError as exc:
            messagebox.showerror("입력 오류", str(exc))
            return False
        self.cancel_row_edit()
        if index is None:
            self.routes.append(route)
            if self.manage_search_var.get().strip() and not matches_route_query(route, self.manage_search_var.get()):
                self.manage_search_var.set("")
        else:
            self.routes[index] = route
        self.save()
        return True

    def copy_route_row(self) -> None:
        if self.edit_state and not self.commit_row_edit():
            return
        sel = self.tree.selection()
        if not sel or not sel[0].isdigit():
            messagebox.showinfo("안내", "복사할 노선을 먼저 선택하세요.")
            return
        idx = int(sel[0])
        src = self.routes[idx]
        new_idx = idx + 1
        self.routes.insert(new_idx, {**src, "days": list(src["days"])})
        self.save()
        new_iid = str(new_idx)
        self.tree.selection_set(new_iid)
        self.tree.focus(new_iid)
        self.tree.see(new_iid)
        self.tree.focus_set()

    def delete(self) -> None:
        self.cancel_row_edit()
        sel = self.tree.selection()
        if sel and messagebox.askyesno("삭제", "선택한 노선을 삭제할까요?"):
            del self.routes[int(sel[0])]
            self.save()

    def save(self) -> None:
        c.save_routes(ROUTES_PATH, self.routes)
        self.refresh_tree()
        self.refresh_jobs()

    def export_csv(self) -> None:
        if self.edit_state and not self.commit_row_edit():
            return
        path = filedialog.asksaveasfilename(
            title="노선 목록 CSV 내보내기",
            defaultextension=".csv",
            initialdir=str(BASE_DIR),
            initialfile="sabre-routes.csv",
            filetypes=[("CSV 파일", "*.csv"), ("모든 파일", "*.*")],
        )
        if not path:
            return
        try:
            c.export_routes_csv(Path(path), self.routes)
        except OSError as exc:
            messagebox.showerror("CSV 내보내기 오류", str(exc))
            return
        messagebox.showinfo("완료", f"{len(self.routes)}개 노선을 CSV로 내보냈습니다.\n{path}")

    def import_csv(self) -> None:
        self.cancel_row_edit()
        path = filedialog.askopenfilename(
            title="노선 목록 CSV 불러오기",
            initialdir=str(BASE_DIR),
            filetypes=[("CSV 파일", "*.csv"), ("모든 파일", "*.*")],
        )
        if not path:
            return
        try:
            routes = c.import_routes_csv(Path(path))
        except (OSError, ValueError) as exc:
            messagebox.showerror("CSV 불러오기 오류", str(exc))
            return
        if not messagebox.askyesno("CSV 불러오기", f"{len(routes)}개 노선을 불러와 현재 목록({len(self.routes)}개)을 교체할까요?"):
            return
        self.routes = routes
        self.save()
        messagebox.showinfo("완료", f"{len(routes)}개 노선을 반영했습니다.")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

