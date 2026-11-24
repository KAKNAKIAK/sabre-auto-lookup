"""세이버자동조회 CLI: AI 에이전트·배치 자동화용 명령줄 실행기(진행 로그=stderr, 최종 JSON=stdout)."""
from __future__ import annotations

import argparse
import ctypes
import os
import json
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook

import sabre_core as c
import sabre_terminal as t

BASE_DIR = Path(__file__).resolve().parent
ROUTES_PATH = BASE_DIR / "sabre-routes.json"
CONFIG_PATH = BASE_DIR / "sabre-config.json"
PORTABLE_DIR = BASE_DIR / "release" / "SabreAutoLookup"
LOGS_DIR = BASE_DIR / "logs"


def resolve_routes_path(explicit: str | None = None, base_dir: Path = BASE_DIR) -> Path:
    if explicit:
        return Path(explicit)
    portable = base_dir / "release" / "SabreAutoLookup" / "sabre-routes.json"
    local = base_dir / "sabre-routes.json"
    if portable.exists():
        try:
            if c.load_routes(portable):
                return portable
        except Exception:
            pass
    return local
ALIASES = {"충칭": "중경"}


def _split_csv(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def load_config(path: Path = CONFIG_PATH) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    port_cfg_p = path.parent / "release" / "SabreAutoLookup" / "sabre-config.json"
    if port_cfg_p.exists() and port_cfg_p.resolve() != path.resolve():
        try:
            pcfg = json.loads(port_cfg_p.read_text(encoding="utf-8"))
            if str(pcfg.get("outputRoot") or "").strip():
                cfg["outputRoot"] = str(pcfg["outputRoot"]).strip()
        except Exception:
            pass
    cfg["_profile_dir"] = str(BASE_DIR / ".chrome-sabre-profile")
    return cfg


def select_jobs(routes: list[dict], *, groups: list[str] | None = None, regions: list[str] | None = None,
                airlines: list[str] | None = None, days_filter: list[int] | None = None,
                select_all: bool = False) -> list[tuple[dict, int]]:
    g_set = {g.upper() for g in (groups or [])}
    r_set = {ALIASES.get(r, r) for r in (regions or [])}
    a_set = {a.upper() for a in (airlines or [])}
    d_set = set(days_filter or [])
    if not (select_all or g_set or r_set or a_set):
        return []
    jobs: list[tuple[dict, int]] = []
    for route in routes:
        if not route.get("enabled", True) or not c.is_complete_route(route):
            continue
        rg = c.route_group(route)
        if g_set and rg not in g_set:
            continue
        if r_set and c.route_region(route) not in r_set:
            continue
        if a_set and route["airline"].upper() not in a_set:
            continue
        for d in route["days"]:
            if not d_set or d in d_set:
                jobs.append((route, d))
    return jobs


def summarize_workbook(path: Path) -> dict:
    wb = load_workbook(path, read_only=True)
    try:
        vals = [row[1] for row in wb.active.iter_rows(min_row=2, values_only=True)]
    finally:
        wb.close()
    return {
        "file": str(path),
        "totalDays": len(vals),
        "fares": sum(isinstance(v, int) for v in vals),
        "soldOut": sum(v == c.SOLD for v in vals),
        "errors": sum(v == c.ERR for v in vals),
    }


def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return False
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _write_json(path: Path, data: dict) -> None:
    c._atomic_write_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _read_active_lock(logs_dir: Path = LOGS_DIR) -> int | None:
    lock_p = logs_dir / "batch.lock"
    if not lock_p.exists():
        return None
    try:
        pid = int(json.loads(lock_p.read_text(encoding="utf-8")).get("pid") or 0)
    except Exception:
        pid = 0
    if pid and _pid_alive(pid):
        return pid
    lock_p.unlink(missing_ok=True)
    return None


def login_with_otp_retry(
    cfg: dict,
    log,
    stop: threading.Event,
    stage1_interval: float = 300.0,
    stage1_resends: int = 5,
    stage2_interval: float = 600.0,
    stage2_attempts: int = 3,
    sleep_fn=time.sleep,
) -> tuple[bool, int, str]:
    """1단계(5분×5회 재전송) 실패 시 2단계(10분 간격 3회)로 모바일 OTP 승인을 재시도한다."""
    auth_failed = False

    def wrapped_log(msg: str, prog=None) -> None:
        nonlocal auth_failed
        if "아이디/비밀번호 오류" in str(msg):
            auth_failed = True
        log(msg, prog)

    attempts = 1
    log("[로그인 1단계] 5분 간격 최대 5회 Okta 푸시 대기 시작")
    if t.launch_and_login(cfg, wrapped_log, stop, push_resend_interval=stage1_interval, max_push_resends=stage1_resends):
        return True, attempts, ""
    if auth_failed:
        return False, attempts, "아이디/비밀번호 오류로 로그인 중단"
    for idx in range(1, stage2_attempts + 1):
        if stop.is_set():
            return False, attempts, "중단됨"
        log(f"[로그인 2단계 {idx}/{stage2_attempts}] {int(stage2_interval // 60)}분 대기 후 재시도")
        sleep_fn(stage2_interval)
        if stop.is_set():
            return False, attempts, "중단됨"
        attempts += 1
        if t.launch_and_login(cfg, wrapped_log, stop, force_relogin=True, push_resend_interval=90.0, max_push_resends=0):
            return True, attempts, ""
        if auth_failed:
            return False, attempts, "아이디/비밀번호 오류로 로그인 중단"
    return False, attempts, "모바일 OTP 미승인으로 로그인 실패"


def read_batch_status(day_str: str | None = None, logs_dir: Path = LOGS_DIR) -> dict:
    day = (day_str or date.today().strftime("%Y%m%d")).replace("-", "").strip()
    res_p = logs_dir / f"batch_{day}.json"
    log_p = logs_dir / f"batch_{day}.log"
    if not res_p.exists():
        return {"ok": False, "status": "not_found", "date": day, "resultFile": str(res_p)}
    data = json.loads(res_p.read_text(encoding="utf-8"))
    pid = int(data.get("pid") or 0)
    if data.get("status") == "running":
        data["pidAlive"] = _pid_alive(pid)
        if not data["pidAlive"]:
            data["status"] = "crashed"
            data["ok"] = False
    if log_p.exists():
        lines = [ln for ln in log_p.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
        data["recentLogs"] = lines[-8:]
    data["resultFile"] = str(res_p)
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="세이버자동조회 CLI (stdout=JSON, stderr=진행 로그)")
    ap.add_argument("--list", action="store_true", help="등록된 노선그룹/노선 목록 JSON 출력")
    ap.add_argument("--login", action="store_true", help="Sabre 로그인(및 세션 확인)만 실행")
    ap.add_argument("--otp-retry", action="store_true", help="모바일 OTP 2단계 재시도(5분×5회 → 10분×3회) 적용")
    ap.add_argument("--detach", action="store_true", help="백그라운드 독립 프로세스로 실행 후 즉시 JSON 반환")
    ap.add_argument("--status", nargs="?", const="", default=None, help="배치 실행 결과 확인 (생략=오늘, 또는 YYYYMMDD)")
    ap.add_argument("--result-file", help=argparse.SUPPRESS)
    ap.add_argument("--log-file", help=argparse.SUPPRESS)
    ap.add_argument("--all", action="store_true", help="사용 중인 모든 노선·항공일수 조회")
    ap.add_argument("--group", help="노선그룹 쉼표 구분 (예: ICN-TAO,ICN-CKG)")
    ap.add_argument("--region", help="지역명 쉼표 구분 (예: 중경,칭다오)")
    ap.add_argument("--airline", help="항공사 코드 쉼표 구분 (예: KE,CA)")
    ap.add_argument("--days", help="항공일수(+N) 필터 쉼표 구분 (예: 2,3)")
    ap.add_argument("--start", help="조회 시작일 YYYY-MM-DD (기본: 오늘+3일)")
    ap.add_argument("--end", help="조회 종료일 YYYY-MM-DD (생략 시 노선별 종료일)")
    ap.add_argument("--routes", help="노선 JSON 파일 경로 지정 (기본: 같은 폴더의 sabre-routes.json)")
    ap.add_argument("--no-bg", action="store_true", help="브라우저 창을 최소화하지 않음")
    args = ap.parse_args(argv)

    if args.status is not None:
        st = read_batch_status(args.status or None)
        _emit(st)
        return 0 if st.get("status") != "not_found" else 1

    routes_path = resolve_routes_path(args.routes)
    routes = c.load_routes(routes_path)
    log_fp = None
    if args.log_file:
        Path(args.log_file).parent.mkdir(parents=True, exist_ok=True)
        log_fp = open(args.log_file, "a", encoding="utf-8")

    def log(msg: str, _prog=None) -> None:
        line = f"{datetime.now():%H:%M:%S} {msg}"
        print(line, file=sys.stderr, flush=True)
        if log_fp is not None:
            log_fp.write(line + "\n")
            log_fp.flush()

    if args.list:
        grouped = c.group_routes(routes)
        _emit({"ok": True, "routesPath": str(routes_path), "groups": list(grouped.keys()),
               "routes": [r for r in routes if r.get("enabled", True) and c.is_complete_route(r)]})
        return 0

    cfg = load_config()
    stop = threading.Event()
    if args.login:
        if args.otp_retry:
            ok, attempts, reason = login_with_otp_retry(cfg, log, stop)
            _emit({"ok": ok, "loginAttempts": attempts, **({"error": reason} if reason else {})})
        else:
            ok = t.launch_and_login(cfg, log, stop)
            _emit({"ok": ok})
        return 0 if ok else 1

    try:
        days_filter = [int(x) for x in _split_csv(args.days)] if args.days else None
        start = date.fromisoformat(args.start) if args.start else date.today() + timedelta(days=3)
        end_override = date.fromisoformat(args.end) if args.end else None
    except ValueError as exc:
        _emit({"ok": False, "error": f"인자 형식 오류: {exc}"})
        return 1

    jobs = select_jobs(routes, groups=_split_csv(args.group), regions=_split_csv(args.region),
                       airlines=_split_csv(args.airline), days_filter=days_filter, select_all=args.all)
    if not jobs:
        _emit({"ok": False, "error": "일치하는 조회 대상이 없습니다. --list 로 등록 노선을 확인하세요."})
        return 1

    if args.detach:
        active_pid = _read_active_lock()
        if active_pid:
            _emit({"ok": False, "alreadyRunning": True, "pid": active_pid, "error": f"이미 실행 중인 배치가 있습니다(PID {active_pid})."})
            return 1
        today_str = date.today().strftime("%Y%m%d")
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        res_p = Path(args.result_file) if args.result_file else (LOGS_DIR / f"batch_{today_str}.json")
        log_p = Path(args.log_file) if args.log_file else (LOGS_DIR / f"batch_{today_str}.log")
        child_cmd = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
                     "--result-file", str(res_p), "--log-file", str(log_p)]
        if args.otp_retry:
            child_cmd.append("--otp-retry")
        if args.all:
            child_cmd.append("--all")
        for flag, val in (("--group", args.group), ("--region", args.region), ("--airline", args.airline),
                          ("--days", args.days), ("--start", args.start), ("--end", args.end), ("--routes", str(routes_path))):
            if val:
                child_cmd += [flag, val]
        if args.no_bg:
            child_cmd.append("--no-bg")
        flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        proc = subprocess.Popen(child_cmd, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        init_meta = {
            "ok": True,
            "status": "running",
            "pid": proc.pid,
            "startedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "start": start.isoformat(),
            "groups": _split_csv(args.group),
            "routesPath": str(routes_path),
            "logFile": str(log_p),
        }
        _write_json(LOGS_DIR / "batch.lock", {"pid": proc.pid, "startedAt": init_meta["startedAt"]})
        _write_json(res_p, init_meta)
        _emit({"ok": True, "detached": True, "pid": proc.pid, "resultFile": str(res_p), "logFile": str(log_p)})
        return 0

    res_path = Path(args.result_file) if args.result_file else None
    lock_path = LOGS_DIR / "batch.lock" if res_path else None
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t0, today = time.monotonic(), date.today()
    completed, failed, group_summaries = [], [], []
    login_attempts = 0

    def _save_progress(status: str, ok_flag: bool, error: str = "") -> dict:
        payload = {
            "ok": ok_flag,
            "status": status,
            "pid": os.getpid(),
            "startedAt": started_at,
            "start": start.isoformat(),
            "groups": _split_csv(args.group),
            "loginAttempts": login_attempts,
            "elapsedSec": round(time.monotonic() - t0, 1),
            "completed": completed,
            "failed": failed,
            "groupSummaries": group_summaries,
        }
        if status != "running":
            payload["finishedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if error:
            payload["error"] = error
        if args.log_file:
            payload["logFile"] = args.log_file
        if res_path is not None:
            _write_json(res_path, payload)
        return payload

    try:
        if lock_path is not None:
            _write_json(lock_path, {"pid": os.getpid(), "startedAt": started_at})
        if args.otp_retry:
            ok_login, login_attempts, reason = login_with_otp_retry(cfg, log, stop)
            if not ok_login:
                payload = _save_progress("failed", False, error=reason)
                _emit(payload)
                return 1
        out_root = cfg.get("outputRoot")
        planned, issues = c.plan_jobs(jobs, start, end_override)
        for msg in issues:
            failed.append({"job": msg.split(":", 1)[0], "reason": msg.split(":", 1)[1].strip()})
            log(f"제외: {msg}")
        by_group: dict[str, list[tuple[dict, int, date, date]]] = {}
        for item in planned:
            by_group.setdefault(c.route_group(item[0]), []).append(item)
        aborted = False
        seq = 0
        for rg, grp_items in by_group.items():
            is_multi = len(grp_items) >= 2
            grp_done: list[tuple[dict, int, Path]] = []
            for route, days, job_start, end in grp_items:
                seq += 1
                name = f"{rg} {c.route_region(route)} {c.flight_pair_label(route)} +{days}"
                log(f"시작: {name} ({job_start} ~ {end})")
                job_out = c.temp_job_path(route, days, job_start, today, seq=seq, root=out_root) if is_multi else None
                try:
                    path = t.run_job(route, days, job_start, end, today, log, stop, background=not args.no_bg, cfg=cfg, out_path=job_out)
                except Exception as exc:
                    failed.append({"job": name, "reason": str(exc)})
                    log(f"실패: {name} - {exc}")
                    if isinstance(exc, (t.SessionExpired, RuntimeError)):
                        aborted = True
                        break
                    continue
                if path:
                    completed.append({"job": name, **summarize_workbook(path)})
                    grp_done.append((route, days, path))
                else:
                    failed.append({"job": name, "reason": "중단됨"})
                    aborted = True
                    break
            if len(grp_done) >= 2:
                for sum_path in c.save_group_summaries({rg: grp_done}, today, root=out_root):
                    group_summaries.append(str(sum_path))
                    log(f"그룹 최저가 통합 완료: {sum_path}")
            elif len(grp_done) == 1 and is_multi:
                r0, d0, p0 = grp_done[0]
                final_p = c.output_path(r0, d0, today, root=out_root)
                final_p.parent.mkdir(parents=True, exist_ok=True)
                os.replace(p0, final_p)
                completed[-1]["file"] = str(final_p)
            _save_progress("running", True)
            if aborted:
                break
        tmp_dir = (Path(str(out_root).strip()) if str(out_root or "").strip() else c.OUTPUT_ROOT) / ".tmp_work"
        if tmp_dir.exists() and not any(tmp_dir.iterdir()):
            tmp_dir.rmdir()

        ok = bool(completed) and not failed
        payload = _save_progress("completed" if ok else "failed", ok)
        _emit(payload)
        return 0 if ok else 1
    finally:
        if lock_path is not None and lock_path.exists():
            try:
                if int(json.loads(lock_path.read_text(encoding="utf-8")).get("pid") or 0) == os.getpid():
                    lock_path.unlink(missing_ok=True)
            except Exception:
                lock_path.unlink(missing_ok=True)
        if log_fp is not None:
            log_fp.close()


if __name__ == "__main__":
    raise SystemExit(main())

