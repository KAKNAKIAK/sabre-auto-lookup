"""세이버자동조회 공통 로직: 날짜, 화면 파싱, 판정, 엑셀 저장."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook, load_workbook

OUTPUT_ROOT = Path(r"G:\내 드라이브\안티그래비티\workspace\04. 요금조회\01. 항공")
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
PREMIUM = set("FAJCDIZR")
SOLD = "예약마감"
ERR = "조회오류"
WPNCB_SOLD = ("UC SEG STATUS NOT ALLOWED", "NCB RESTRICTED ON WAILISTED", "NCB RESTRICTED ON WAITLISTED",
              "NO FARE FOR CLASS USED", "NO FARE", "UNABLE TO REBOOK", "NO COMBINABLE FARES")
CITY = {"ICN": "SEL", "GMP": "SEL", "NRT": "TYO", "HND": "TYO", "PVG": "SHA", "PEK": "BJS", "PKX": "BJS"}
ORIGIN_LABEL = {"ICN": "인천", "PUS": "부산", "GMP": "김포"}


def ddmmm(d: date) -> str:
    return f"{d.day:02d}{MONTHS[d.month - 1]}"


def flight_no(value: str, airline: str) -> int:
    text = re.sub(r"\s+", "", str(value).upper())
    if text.startswith(airline.upper()):
        text = text[len(airline):]
    return int(re.sub(r"\D", "", text) or 0)


def parse_availability(text: str) -> list[dict]:
    """가용 화면 글자(API 원본 호스트 텍스트 및 UI innerText 모두)를 [{line, carrier, number, classes}]로 바꾼다."""
    # 1) API 원본 호스트 형식: " 1CA     440 J6 C6 D6 ... ICNCKG ...\n             R3 Y9 B9 ..."
    host_head = re.compile(r"^\s*(\d{1,2})((?=[A-Z0-9]*[A-Z])[A-Z0-9]{2}(?:/[A-Z0-9]{2})?)\s+(\d{1,4})\s+(.*)$")
    pair_re = re.compile(r"^[A-Z][0-9LCXRS*./-]$")
    host_rows: list[dict] = []
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
        m = host_head.match(lines[idx])
        if m:
            classes: dict[str, int] = {}
            for tok in m.group(4).split():
                if pair_re.match(tok):
                    classes[tok[0]] = int(tok[1]) if tok[1].isdigit() else 0
                elif classes:
                    break
            j = idx + 1
            while j < len(lines) and lines[j].startswith("      ") and not host_head.match(lines[j]):
                # Sabre 호스트 가용 화면 마지막 줄은 끝에 마침표(.)가 붙는다(예: "K9.", "GC.").
                cont = [tok.rstrip(".") for tok in lines[j].split()]
                if cont and all(pair_re.match(tok) for tok in cont):
                    for tok in cont:
                        classes[tok[0]] = int(tok[1]) if tok[1].isdigit() else 0
                    j += 1
                else:
                    break
            if classes:
                host_rows.append({"line": int(m.group(1)), "carrier": m.group(2), "number": int(m.group(3)), "classes": classes})
                idx = j
                continue
        idx += 1
    if host_rows:
        return host_rows

    # 2) UI innerText 형식: 클래스가 공백 없이(예: J6C6Y9B9) 또는 공백으로 나뉘어 출력됨
    toks = text.split()
    carrier = re.compile(r"^(?=.*[A-Z])[A-Z0-9]{2}(/[A-Z0-9]{2})?$")
    seat_block = re.compile(r"^(?:[A-Z][0-9LCXRS*./-])+$")
    rows, i = [], 0
    while i < len(toks) - 2:
        a, b, c = toks[i], toks[i + 1], toks[i + 2]
        if a.isdigit() and 1 <= int(a) <= 99 and carrier.match(b) and c.isdigit():
            j, classes = i + 3, {}
            while j < len(toks) and seat_block.match(toks[j]):
                blk = toks[j]
                for p in range(0, len(blk), 2):
                    classes[blk[p]] = int(blk[p + 1]) if blk[p + 1].isdigit() else 0
                j += 1
            if classes:
                rows.append({"line": int(a), "carrier": b, "number": int(c), "classes": classes})
                i = j
                continue
        i += 1
    return rows


def find_row(rows: list[dict], airline: str, number: int) -> dict | None:
    return next((r for r in rows if r["carrier"] == airline and r["number"] == number), None)


def open_class(classes: dict) -> str | None:
    """좌석이 남은 이코노미 클래스. Y 우선, 없으면 None(전석 마감)."""
    keys = list(classes.keys())
    if "Y" in classes:
        # Sabre는 객실 등급 순으로 나열하므로 Y부터 끝까지가 이코노미 객실이다.
        economy = {k: classes[k] for k in keys[keys.index("Y"):]}
    else:
        economy = {k: v for k, v in classes.items() if k not in PREMIUM}
    if economy.get("Y", 0) > 0:
        return "Y"
    return next((k for k, v in economy.items() if v > 0), None)


def sell_state(text: str, airline: str = "", number: int = 0, day: str = "") -> str:
    up = re.sub(r"\s+", " ", text.upper())
    if re.search(r"\b(SS|HK|GK)1\b", up):
        if airline and not re.search(rf"\b{airline}\s*0*{number}[A-Z]?\b", up):
            return "error"
        if day and day not in up:
            return "error"
        return "ok"
    if re.search(r"\b(UC|UN|LL|HL|NO)1\b|UNABLE", up):
        return "sold"
    return "error"


def parse_wpncb(text: str, airline: str, origin: str, dest: str, out_no: int = 0, ret_no: int = 0,
                out_d: str = "", ret_d: str = "") -> int | str:
    up = re.sub(r"[ \t]+", " ", text.upper())
    # UI 표("1- KRW340000")와 API 원본("FARE KRW 364000") 모두 지원하며 TOTAL/TAX는 제외한다.
    fare = re.search(r"(?:1-|(?:^|\n)\s*FARE)\s*KRW\s*([\d,]+)", up)
    city = CITY.get(origin, origin)
    dest_city = CITY.get(dest, dest)
    out_leg = f"{city} {airline} {dest}" in up or f"{city} {airline} {dest_city}" in up
    ret_leg = f"{airline} {city}" in up or f"{airline} {origin}" in up
    # Sabre Red Web WPNCB 카드의 innerText는 여정 줄이 접혀 생략될 수 있어, 있을 때만 추가 대조한다.
    has_seg_lines = bool(re.search(rf"\b1 {airline} \d+[A-Z]? \d{{2}}[A-Z]{{3}}\b", up))
    segs_ok = True
    if has_seg_lines and out_no and ret_no:
        seg1 = re.search(rf"\b1 {airline} 0*{out_no} ?[A-Z]? {out_d}\b[^\n]*\b(SS|HK|GK)1\b", up)
        seg2 = re.search(rf"\b2 {airline} 0*{ret_no} ?[A-Z]? {ret_d}\b[^\n]*\b(SS|HK|GK)1\b", up)
        segs_ok = bool(seg1 and seg2)
    if fare and out_leg and ret_leg and segs_ok:
        return int(fare.group(1).replace(",", ""))
    if any(p in up for p in WPNCB_SOLD):
        return SOLD
    return ERR


def output_path(route: dict, days: int, today: date) -> Path:
    name = f"{today:%Y%m%d} 조회_{route['origin']}{route['destination']}_{route['airline']}_플러스{days}.xlsx"
    return OUTPUT_ROOT / route["region"] / name


def basis_text(route: dict, days: int) -> str:
    dest = "충칭" if route["region"] == "중경" else route["region"]
    return f"{ORIGIN_LABEL.get(route['origin'], route['origin'])}/{dest} {route['airline']} *+ {days} 조회기준"


def save_workbook(path: Path, basis: str, results: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.append(["날짜", "운임", basis])
    for d in sorted(results):
        ws.append([d.isoformat(), results[d]])
    wb.save(path)


def verify_workbook(path: Path, basis: str, start: date, end: date) -> None:
    ws = load_workbook(path).active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    expected = [(start + timedelta(n)).isoformat() for n in range((end - start).days + 1)]
    if ws["C1"].value != basis:
        raise ValueError("C1 조회기준 불일치")
    if [r[0] for r in rows] != expected:
        raise ValueError("날짜 누락 또는 중복")
    if not all(isinstance(r[1], int) or r[1] in (SOLD, ERR) for r in rows):
        raise ValueError("운임 칸 형식 오류")


def load_routes(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")).get("routes", []) if path.exists() else []


def save_routes(path: Path, routes: list[dict]) -> None:
    path.write_text(json.dumps({"schema": "sabre-routes-v1", "routes": routes}, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def normalize_route(form: dict) -> dict:
    days = sorted({int(x) for x in re.findall(r"\d+", str(form.get("days", "")))})
    keys = ("region", "origin", "destination", "airline", "depFlight", "retFlight", "endDate")
    route = {k: str(form.get(k, "")).strip() for k in keys}
    for k in ("origin", "destination", "airline", "depFlight", "retFlight"):
        route[k] = route[k].upper()
    if not all(route.values()) or not days:
        raise ValueError("모든 칸을 입력하세요. 항공일수는 2,3 처럼 쉼표로 여러 개 입력합니다.")
    date.fromisoformat(route["endDate"])
    group = str(form.get("routeGroup") or "").strip().upper() or f"{route['origin']}-{route['destination']}"
    return {"routeGroup": group, **route, "days": days, "enabled": bool(form.get("enabled", True))}


def group_routes(routes: list[dict]) -> dict[str, list[dict]]:
    """사용 중인 노선을 노선그룹(routeGroup) 단위로 묶어 순서대로 반환한다."""
    grouped: dict[str, list[dict]] = {}
    for r in routes:
        if not r.get("enabled", True):
            continue
        group = str(r.get("routeGroup") or f"{r['origin']}-{r['destination']}").strip().upper()
        grouped.setdefault(group, []).append(r)
    return grouped

