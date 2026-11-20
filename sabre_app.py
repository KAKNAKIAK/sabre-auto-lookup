"""세이버자동조회 화면: 조회 노선 관리 + 자동조회."""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

import sabre_core as c
import sabre_terminal as t

BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
ROUTES_PATH = BASE_DIR / "sabre-routes.json"
CONFIG_PATH = BASE_DIR / "sabre-config.json"
FIELDS = (("노선그룹", "routeGroup"), ("지역명", "region"), ("출발지", "origin"), ("도착지", "destination"),
          ("항공사", "airline"), ("출국편", "depFlight"), ("귀국편", "retFlight"), ("항공일수(+N)", "days"), ("조회종료일", "endDate"))


def show(route: dict, key: str) -> str:
    if key == "routeGroup":
        return str(route.get("routeGroup") or f"{route['origin']}-{route['destination']}")
    return ", ".join(map(str, route[key])) if key == "days" else str(route[key])


class App:
    def __init__(self, root: tk.Tk):
        self.root, self.stop, self.events = root, threading.Event(), queue.Queue()
        root.title("세이버자동조회 (Sabre 실시간 운임)")
        root.geometry("1120x780")
        self.routes = c.load_routes(ROUTES_PATH)
        self.group_vars: dict[str, tk.BooleanVar] = {}
        self.job_entries: list[tuple[str, tk.BooleanVar, ttk.Checkbutton, dict, int]] = []
        self.detail_visible = True
        self.detail_summary_var = tk.StringVar(value="선택 0개 노선그룹 / 0개 항목")
        self.detail_toggle_var = tk.StringVar(value="세부 접기")
        nb = ttk.Notebook(root)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        auto, manage = ttk.Frame(nb, padding=8), ttk.Frame(nb, padding=8)
        nb.add(auto, text="자동조회")
        nb.add(manage, text="조회 노선 관리")
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
        ttk.Button(top, text="브라우저 실행/로그인", command=self.login).pack(side=tk.RIGHT, padx=4)

        # 1단: 노선그룹 선택 (기존 항공자동조회 구조)
        grp_box = ttk.LabelFrame(tab, text="노선그룹 선택", padding=(8, 6))
        grp_box.pack(fill=tk.X, pady=(8, 0))
        grp_bar = ttk.Frame(grp_box)
        grp_bar.pack(fill=tk.X, pady=(0, 4))
        self.bg_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grp_bar, text="백그라운드(창 최소화)", variable=self.bg_var).pack(side=tk.LEFT)
        ttk.Button(grp_bar, text="선택 해제", command=lambda: self.set_all_groups(False)).pack(side=tk.RIGHT)
        ttk.Button(grp_bar, text="전체 선택", command=lambda: self.set_all_groups(True)).pack(side=tk.RIGHT, padx=4)
        ttk.Button(grp_bar, text="엑셀 폴더 열기", command=self.open_output_dir).pack(side=tk.RIGHT, padx=4)
        self.group_checks_frame = ttk.Frame(grp_box)
        self.group_checks_frame.pack(fill=tk.X)

        # 2단: 항공사 · 편명 · 항공일수 세부 선택 (그룹별 카드)
        det_box = ttk.LabelFrame(tab, text="항공사 · 편명 · 항공일수 세부 선택", padding=(8, 6))
        det_box.pack(fill=tk.X, pady=(8, 0))
        det_bar = ttk.Frame(det_box)
        det_bar.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(det_bar, textvariable=self.detail_summary_var).pack(side=tk.LEFT)
        ttk.Button(det_bar, textvariable=self.detail_toggle_var, width=9, command=self.toggle_detail).pack(side=tk.RIGHT)
        ttk.Button(det_bar, text="선택 해제", command=lambda: self.set_all_jobs(False)).pack(side=tk.RIGHT, padx=4)
        ttk.Button(det_bar, text="전체 선택", command=lambda: self.set_all_jobs(True)).pack(side=tk.RIGHT)
        self.detail_container = ttk.Frame(det_box)
        self.detail_container.pack(fill=tk.X)
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
        self.progress.pack(fill=tk.X, pady=6)
        self.log_box = tk.Text(tab, height=14)
        self.log_box.pack(fill=tk.BOTH, expand=True)
        self.refresh_jobs()

    def open_output_dir(self) -> None:
        c.OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        os.startfile(str(c.OUTPUT_ROOT))

    def toggle_detail(self) -> None:
        self.detail_visible = not self.detail_visible
        if self.detail_visible:
            self.detail_container.pack(fill=tk.X)
            self.detail_toggle_var.set("세부 접기")
        else:
            self.detail_container.pack_forget()
            self.detail_toggle_var.set("세부 펼치기")

    def on_group_toggle(self, group: str) -> None:
        selected = bool(self.group_vars[group].get())
        for g, var, _, _, _ in self.job_entries:
            if g == group:
                var.set(selected)
        self.update_detail_states()

    def on_job_toggle(self, group: str, var: tk.BooleanVar) -> None:
        if var.get() and not self.group_vars[group].get():
            self.group_vars[group].set(True)
        self.update_detail_states()

    def set_group_jobs(self, group: str, selected: bool) -> None:
        if selected:
            self.group_vars[group].set(True)
        for g, var, _, _, _ in self.job_entries:
            if g == group:
                var.set(selected)
        self.update_detail_states()

    def set_all_groups(self, selected: bool) -> None:
        for var in self.group_vars.values():
            var.set(selected)
        for _, var, _, _, _ in self.job_entries:
            var.set(selected)
        self.update_detail_states()

    def set_all_jobs(self, selected: bool) -> None:
        if selected:
            for var in self.group_vars.values():
                var.set(True)
        for _, var, _, _, _ in self.job_entries:
            var.set(selected)
        self.update_detail_states()

    def update_detail_states(self) -> None:
        for g, _, cb, _, _ in self.job_entries:
            cb.configure(state=tk.NORMAL if self.group_vars[g].get() else tk.DISABLED)
        sel = self.selected_jobs()
        grp_cnt = len({show(r, "routeGroup") for r, _ in sel})
        self.detail_summary_var.set(f"선택 {grp_cnt}개 노선그룹 / {len(sel)}개 조회항목")

    def selected_jobs(self) -> list[tuple[dict, int]]:
        return [(r, d) for g, var, _, r, d in self.job_entries if self.group_vars[g].get() and var.get()]

    def refresh_jobs(self) -> None:
        for w in self.group_checks_frame.winfo_children():
            w.destroy()
        for w in self.jobs_frame.winfo_children():
            w.destroy()
        self.group_vars.clear()
        self.job_entries.clear()
        grouped = c.group_routes(self.routes)
        groups = list(grouped.keys())
        for idx, group in enumerate(groups):
            var = tk.BooleanVar(value=False)
            self.group_vars[group] = var
            region = grouped[group][0]["region"]
            ttk.Checkbutton(
                self.group_checks_frame,
                text=f"{group} ({region})",
                variable=var,
                command=lambda g=group: self.on_group_toggle(g),
            ).grid(row=idx // 5, column=idx % 5, padx=(0, 12), pady=2, sticky="w")
        for col in range(3):
            self.jobs_frame.columnconfigure(col, weight=1, uniform="sabre_group")
        for idx, group in enumerate(groups):
            card = ttk.LabelFrame(self.jobs_frame, text=group, padding=(6, 4))
            card.grid(row=idx // 3, column=idx % 3, padx=(0, 6), pady=(0, 6), sticky="nsew")
            tb = ttk.Frame(card)
            tb.pack(fill=tk.X, pady=(0, 2))
            ttk.Button(tb, text="전체", width=5, command=lambda g=group: self.set_group_jobs(g, True)).pack(side=tk.LEFT)
            ttk.Button(tb, text="해제", width=5, command=lambda g=group: self.set_group_jobs(g, False)).pack(side=tk.LEFT, padx=4)
            for route in grouped[group]:
                for days in route["days"]:
                    var = tk.BooleanVar(value=False)
                    lbl = f"{route['region']} {route['depFlight']}/{route['retFlight']} +{days}"
                    cb = ttk.Checkbutton(card, text=lbl, variable=var,
                                         command=lambda g=group, v=var: self.on_job_toggle(g, v))
                    cb.pack(anchor="w")
                    self.job_entries.append((group, var, cb, route, days))
        self.update_detail_states()

    def load_cfg(self) -> dict:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
        cfg["_profile_dir"] = str(BASE_DIR / "output" / "chrome-sabre-profile")
        return cfg

    def login(self) -> None:
        cfg = self.load_cfg()
        self.stop.clear()
        threading.Thread(target=t.launch_and_login, args=(cfg, self.log, self.stop), daemon=True).start()

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
            name = f"{route['region']} {route['airline']} +{days}"
            end = end_override or date.fromisoformat(route["endDate"])
            if end < start:
                failed.append(f"{name}: 종료일이 시작일보다 빠름")
                continue
            self.log(f"시작: {name} ({start} ~ {end})")
            try:
                path = t.run_job(route, days, start, end, today, self.log, self.stop,
                                 background=self.bg_var.get(), cfg=cfg)
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

    def pump(self) -> None:
        while not self.events.empty():
            msg, progress = self.events.get()
            self.log_box.insert(tk.END, f"{datetime.now():%H:%M:%S} {msg}\n")
            self.log_box.see(tk.END)
            if progress:
                self.progress.configure(maximum=progress[1], value=progress[0])
        self.root.after(200, self.pump)

    # ----- 조회 노선 관리 -----
    def build_manage(self, tab: ttk.Frame) -> None:
        keys = [k for _, k in FIELDS] + ["enabled"]
        self.tree = ttk.Treeview(tab, columns=keys, show="headings", height=14)
        for label, key in FIELDS + (("사용", "enabled"),):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=100, anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        form = ttk.Frame(tab)
        form.pack(fill=tk.X, pady=8)
        self.form = {}
        for col, (label, key) in enumerate(FIELDS):
            ttk.Label(form, text=label).grid(row=0, column=col, sticky="w")
            self.form[key] = tk.StringVar()
            ttk.Entry(form, textvariable=self.form[key], width=11).grid(row=1, column=col, padx=2)
        self.enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="사용", variable=self.enabled).grid(row=1, column=len(FIELDS))
        btns = ttk.Frame(tab)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="추가", command=lambda: self.apply(True)).pack(side=tk.LEFT)
        ttk.Button(btns, text="선택 수정", command=lambda: self.apply(False)).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="선택 삭제", command=self.delete).pack(side=tk.LEFT)
        ttk.Button(btns, text="JSON 다시 읽기", command=self.reload_routes).pack(side=tk.LEFT, padx=8)
        ttk.Label(btns, text="노선그룹 빈칸=출발지-도착지 자동입력 / 항공일수 예: 2,3").pack(side=tk.RIGHT)
        self.refresh_tree()

    def reload_routes(self) -> None:
        self.routes = c.load_routes(ROUTES_PATH)
        self.refresh_tree()
        self.refresh_jobs()

    def refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.routes):
            values = [show(r, k) for _, k in FIELDS] + ["사용" if r.get("enabled", True) else "중지"]
            self.tree.insert("", tk.END, iid=str(i), values=values)

    def on_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if sel:
            route = self.routes[int(sel[0])]
            for _, k in FIELDS:
                self.form[k].set(show(route, k))
            self.enabled.set(route.get("enabled", True))

    def apply(self, new: bool) -> None:
        try:
            route = c.normalize_route({**{k: v.get() for k, v in self.form.items()}, "enabled": self.enabled.get()})
        except ValueError as exc:
            messagebox.showerror("입력 오류", str(exc))
            return
        sel = self.tree.selection()
        if new:
            self.routes.append(route)
        elif sel:
            self.routes[int(sel[0])] = route
        else:
            messagebox.showinfo("안내", "수정할 노선을 먼저 선택하세요.")
            return
        self.save()

    def delete(self) -> None:
        sel = self.tree.selection()
        if sel and messagebox.askyesno("삭제", "선택한 노선을 삭제할까요?"):
            del self.routes[int(sel[0])]
            self.save()

    def save(self) -> None:
        c.save_routes(ROUTES_PATH, self.routes)
        self.refresh_tree()
        self.refresh_jobs()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

