# -*- coding: utf-8 -*-
"""세이버자동조회 Windows 셋업 인스톨러 (신규 설치 + --update 자동 교체)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_NAME = "항공운임 조회 (SABRE VER.)"
APP_EXE_NAME = "항공운임 조회 (SABRE VER.).exe"
APP_DIR_NAME = "SabreAutoLookup"
DEFAULT_INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Public")) / APP_DIR_NAME
PRESERVE_IF_EXISTS = {"sabre-routes.json", "sabre-config.json"}


def get_resource_path(relative_path: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent / relative_path


def create_shortcut(target_exe: Path, shortcut_path: Path, icon_path: Path | None = None) -> None:
    icon_loc = str(icon_path if (icon_path and icon_path.exists()) else target_exe)
    try:
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(str(shortcut_path))
        sc.TargetPath = str(target_exe)
        sc.WorkingDirectory = str(target_exe.parent)
        sc.IconLocation = icon_loc
        sc.save()
        return
    except Exception:
        pass
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:SC_PATH);"
        "$s.TargetPath=$env:SC_TARGET;"
        "$s.WorkingDirectory=$env:SC_DIR;"
        "$s.IconLocation=$env:SC_ICON;"
        "$s.Save()"
    )
    env = {
        **os.environ,
        "SC_PATH": str(shortcut_path),
        "SC_TARGET": str(target_exe),
        "SC_DIR": str(target_exe.parent),
        "SC_ICON": icon_loc,
    }
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            env=env,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def extract_member_with_retry(zip_ref: zipfile.ZipFile, member: zipfile.ZipInfo, install_dir: Path, timeout_sec: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_sec
    while True:
        try:
            zip_ref.extract(member, install_dir)
            return
        except PermissionError as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"실행 중인 {APP_NAME}가 종료되지 않아 파일을 교체할 수 없습니다.\n"
                    "프로그램을 닫은 뒤 다시 시도해 주세요."
                ) from exc
            time.sleep(0.5)


def install_payload(payload_zip: Path, install_dir: Path, progress_cb=None) -> Path:
    if not payload_zip.exists():
        raise FileNotFoundError(f"설치 패키지를 찾을 수 없습니다: {payload_zip}")
    install_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(payload_zip, "r") as zf:
        members = zf.infolist()
        total = max(1, len(members))
        for idx, member in enumerate(members, 1):
            base_name = Path(member.filename).name.lower()
            target = install_dir / member.filename
            if base_name in PRESERVE_IF_EXISTS and target.exists():
                continue
            extract_member_with_retry(zf, member, install_dir)
            if progress_cb:
                progress_cb(idx, total)
    return install_dir / APP_EXE_NAME


class InstallerApp:
    def __init__(self, root: tk.Tk, update_dir: Path | None = None) -> None:
        self.root = root
        self.update_dir = update_dir
        self.root.title(f"{APP_NAME} {'업데이트' if update_dir else '설치'}")
        self.root.geometry("500x340")
        self.root.resizable(False, False)

        icon_path = get_resource_path("sabre_icon.ico")
        if icon_path.exists():
            try:
                self.root.iconbitmap(str(icon_path))
            except Exception:
                pass

        self.install_dir_var = tk.StringVar(value=str(update_dir or DEFAULT_INSTALL_DIR))
        self.desktop_sc_var = tk.BooleanVar(value=not bool(update_dir))
        self.start_menu_sc_var = tk.BooleanVar(value=not bool(update_dir))
        self.run_after_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(
            value="자동 업데이트를 준비하고 있습니다..." if update_dir else f"설치 시작을 누르면 {APP_NAME}가 설치됩니다."
        )
        self.progress_var = tk.DoubleVar(value=0)
        self._build_ui()
        if update_dir:
            self.root.after(400, self.start_install)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=f"{APP_NAME} {'자동 업데이트' if self.update_dir else '설치 프로그램'}",
            font=("맑은 고딕", 13, "bold"),
        ).pack(anchor="w", pady=(0, 12))

        dir_box = ttk.LabelFrame(frame, text="설치 경로", padding=10)
        dir_box.pack(fill=tk.X, pady=(0, 10))
        self.dir_entry = ttk.Entry(dir_box, textvariable=self.install_dir_var)
        self.dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.browse_btn = ttk.Button(dir_box, text="찾아보기...", command=self.browse_dir)
        self.browse_btn.pack(side=tk.RIGHT)

        opt_box = ttk.LabelFrame(frame, text="설치 옵션", padding=10)
        opt_box.pack(fill=tk.X, pady=(0, 10))
        ttk.Checkbutton(opt_box, text="바탕화면에 바로가기 만들기", variable=self.desktop_sc_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(opt_box, text="시작 메뉴에 바로가기 만들기", variable=self.start_menu_sc_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(opt_box, text="설치 완료 후 바로 실행", variable=self.run_after_var).pack(anchor="w", pady=2)

        prog_box = ttk.Frame(frame)
        prog_box.pack(fill=tk.X, pady=(6, 10))
        ttk.Progressbar(prog_box, variable=self.progress_var, maximum=100).pack(fill=tk.X)
        ttk.Label(prog_box, textvariable=self.status_var, foreground="#475569").pack(anchor="w", pady=(4, 0))

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, side=tk.BOTTOM)
        self.install_btn = ttk.Button(btn_row, text="설치 시작", command=self.start_install)
        self.install_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self.cancel_btn = ttk.Button(btn_row, text="취소", command=self.root.destroy)
        self.cancel_btn.pack(side=tk.RIGHT)

        if self.update_dir:
            self.dir_entry.configure(state=tk.DISABLED)
            self.browse_btn.configure(state=tk.DISABLED)
            self.install_btn.configure(state=tk.DISABLED)

    def browse_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.install_dir_var.get())
        if chosen:
            self.install_dir_var.set(chosen)

    def start_install(self) -> None:
        install_dir = Path(self.install_dir_var.get()).resolve()
        self.install_btn.configure(state=tk.DISABLED)
        self.status_var.set("파일 설치 중...")
        self.progress_var.set(15)
        self.root.update_idletasks()

        try:
            payload_zip = get_resource_path("payload.zip")

            def _on_prog(idx: int, total: int) -> None:
                self.progress_var.set(15 + int(idx * 70 / total))
                self.root.update_idletasks()

            target_exe = install_payload(payload_zip, install_dir, progress_cb=_on_prog)
            icon_path = install_dir / "assets" / "sabre_icon.ico"

            self.status_var.set("바로가기 구성 중...")
            self.progress_var.set(90)
            self.root.update_idletasks()

            desktop_sc = Path(os.environ.get("USERPROFILE", r"C:\Users\Public")) / "Desktop" / f"{APP_NAME}.lnk"
            start_sc = Path(os.environ.get("APPDATA", r"C:\Users\Public")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"
            if self.desktop_sc_var.get() or (self.update_dir and desktop_sc.exists()):
                create_shortcut(target_exe, desktop_sc, icon_path)
            if self.start_menu_sc_var.get() or (self.update_dir and start_sc.exists()):
                create_shortcut(target_exe, start_sc, icon_path)

            self.progress_var.set(100)
            self.status_var.set("완료되었습니다.")
            self.root.update_idletasks()

            if not self.update_dir:
                messagebox.showinfo("설치 완료", f"{APP_NAME} 설치가 완료되었습니다.\n설치 경로: {install_dir}")

            if self.run_after_var.get() and target_exe.exists():
                os.startfile(str(target_exe))

            self.root.destroy()
        except Exception as exc:
            self.install_btn.configure(state=tk.NORMAL)
            self.status_var.set("설치 실패")
            messagebox.showerror("설치 오류", f"설치 중 오류가 발생했습니다:\n{exc}")


def _parse_update_dir(argv: list[str]) -> Path | None:
    if "--update" in argv:
        idx = argv.index("--update")
        if idx + 1 < len(argv) and argv[idx + 1].strip():
            return Path(argv[idx + 1]).resolve()
        return DEFAULT_INSTALL_DIR
    return None


def main() -> None:
    update_dir = _parse_update_dir(sys.argv[1:])
    root = tk.Tk()
    InstallerApp(root, update_dir=update_dir)
    root.mainloop()


if __name__ == "__main__":
    main()
