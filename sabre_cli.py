"""세이버자동조회 CLI: AI 에이전트·배치 자동화용 명령줄 실행기(진행 로그=stderr, 최종 JSON=stdout)."""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path

from openpyxl import load_workbook

import sabre_core as c
import sabre_terminal as t

BASE_DIR = Path(__file__).resolve().parent
ROUTES_PATH = BASE_DIR / "sabre-routes.json"
CONFIG_PATH = BASE_DIR / "sabre-config.json"
ALIASES = {"충칭": "중경"}


def _split_csv(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def load_config(path: Path = CONFIG_PATH) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    cfg["_profile_dir"] = str(BASE_DIR / "output" / "chrome-sabre-profile")
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="세이버자동조회 CLI (stdout=JSON, stderr=진행 로그)")
    ap.add_argument("--list", action="store_true", help="등록된 노선그룹/노선 목록 JSON 출력")
    ap.add_argument("--login", action="store_true", help="Sabre 로그인(및 세션 확인)만 실행")
    ap.add_argument("--all", action="store_true", help="사용 중인 모든 노선·항공일수 조회")
    ap.add_argument("--group", help="노선그룹 쉼표 구분 (예: ICN-TAO,ICN-CKG)")
    ap.add_argument("--region", help="지역명 쉼표 구분 (예: 중경,칭다오)")
    ap.add_argument("--airline", help="항공사 코드 쉼표 구분 (예: KE,CA)")
    ap.add_argument("--days", help="항공일수(+N) 필터 쉼표 구분 (예: 2,3)")
    ap.add_argument("--start", help="조회 시작일 YYYY-MM-DD (기본: 내일)")
    ap.add_argument("--end", help="조회 종료일 YYYY-MM-DD (생략 시 노선별 종료일)")
    ap.add_argument("--no-bg", action="store_true", help="브라우저 창을 최소화하지 않음")
    args = ap.parse_args(argv)

    routes = c.load_routes(ROUTES_PATH)
    log = lambda msg, _prog=None: print(msg, file=sys.stderr, flush=True)

    if args.list:
        grouped = c.group_routes(routes)
        _emit({"ok": True, "groups": list(grouped.keys()),
               "routes": [r for r in routes if r.get("enabled", True) and c.is_complete_route(r)]})
        return 0

    cfg = load_config()
    stop = threading.Event()
    if args.login:
        ok = t.launch_and_login(cfg, log, stop)
        _emit({"ok": ok})
        return 0 if ok else 1

    try:
        days_filter = [int(x) for x in _split_csv(args.days)] if args.days else None
        start = date.fromisoformat(args.start) if args.start else date.today() + timedelta(days=1)
        end_override = date.fromisoformat(args.end) if args.end else None
    except ValueError as exc:
        _emit({"ok": False, "error": f"인자 형식 오류: {exc}"})
        return 1

    jobs = select_jobs(routes, groups=_split_csv(args.group), regions=_split_csv(args.region),
                       airlines=_split_csv(args.airline), days_filter=days_filter, select_all=args.all)
    if not jobs:
        _emit({"ok": False, "error": "일치하는 조회 대상이 없습니다. --list 로 등록 노선을 확인하세요."})
        return 1

    t0, today = time.monotonic(), date.today()
    completed, failed = [], []
    for route, days in jobs:
        rg = c.route_group(route)
        name = f"{rg} {c.route_region(route)} {route['airline']} +{days}"
        end = end_override or date.fromisoformat(route["endDate"])
        if end < start:
            failed.append({"job": name, "reason": f"종료일({end})이 시작일({start})보다 빠릅니다."})
            continue
        log(f"시작: {name} ({start} ~ {end})")
        try:
            path = t.run_job(route, days, start, end, today, log, stop, background=not args.no_bg, cfg=cfg)
        except Exception as exc:
            failed.append({"job": name, "reason": str(exc)})
            log(f"실패: {name} - {exc}")
            if isinstance(exc, (t.SessionExpired, RuntimeError)):
                break
            continue
        if path:
            completed.append({"job": name, **summarize_workbook(path)})
        else:
            failed.append({"job": name, "reason": "중단됨"})
            break

    ok = bool(completed) and not failed
    _emit({"ok": ok, "elapsedSec": round(time.monotonic() - t0, 1), "completed": completed, "failed": failed})
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

