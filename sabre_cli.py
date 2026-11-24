"""세이버자동조회 CLI: AI 에이전트·배치 자동화용 명령줄 실행기(진행 로그=stderr, 최종 JSON=stdout)."""
from __future__ import annotations

import argparse
import os
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
PORTABLE_DIR = BASE_DIR / "release" / "SabreAutoLookup"


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
    ap.add_argument("--routes", help="노선 JSON 파일 경로 지정 (기본: 같은 폴더의 sabre-routes.json)")
    ap.add_argument("--no-bg", action="store_true", help="브라우저 창을 최소화하지 않음")
    args = ap.parse_args(argv)

    routes_path = resolve_routes_path(args.routes)
    routes = c.load_routes(routes_path)
    log = lambda msg, _prog=None: print(msg, file=sys.stderr, flush=True)

    if args.list:
        grouped = c.group_routes(routes)
        _emit({"ok": True, "routesPath": str(routes_path), "groups": list(grouped.keys()),
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
    group_summaries = []
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
            completed[-1]["path"] = str(final_p)
        if aborted:
            break
    tmp_dir = (Path(str(out_root).strip()) if str(out_root or "").strip() else c.OUTPUT_ROOT) / ".tmp_work"
    if tmp_dir.exists() and not any(tmp_dir.iterdir()):
        tmp_dir.rmdir()

    ok = bool(completed) and not failed
    payload = {"ok": ok, "elapsedSec": round(time.monotonic() - t0, 1), "completed": completed, "failed": failed}
    if group_summaries:
        payload["groupSummaries"] = group_summaries
    _emit(payload)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

