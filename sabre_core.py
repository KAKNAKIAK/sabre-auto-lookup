"""세이버자동조회 공통 로직: 날짜, 화면 파싱, 판정, 엑셀 저장."""
from __future__ import annotations

import csv
import json
import re
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

OUTPUT_ROOT = Path(r"G:\내 드라이브\안티그래비티\workspace\04. 요금조회\01. 항공")
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
PREMIUM = set("FAJCDIZR")
SOLD = "예약마감"
ERR = "조회오류"
WPNCB_SOLD = ("UC SEG STATUS NOT ALLOWED", "NCB RESTRICTED ON WAILISTED", "NCB RESTRICTED ON WAITLISTED",
              "NO FARE FOR CLASS USED", "NO FARE", "UNABLE TO REBOOK", "NO COMBINABLE FARES")
CITY = {"ICN": "SEL", "GMP": "SEL", "NRT": "TYO", "HND": "TYO", "PVG": "SHA", "PEK": "BJS", "PKX": "BJS"}
ORIGIN_LABEL = {"ICN": "인천", "PUS": "부산", "GMP": "김포"}
DEST_REGION = {"CKG": "중경", "HKT": "푸켓", "CNX": "치앙마이", "GUM": "괌", "TAO": "칭다오",
               "DAD": "다낭", "CXR": "나트랑", "PQC": "푸꾸옥", "HAN": "하노이", "SGN": "호치민"}


def route_group(route: dict) -> str:
    rg = str(route.get("routeGroup") or "").strip().upper()
    if rg:
        return rg
    org = str(route.get("origin") or "").strip().upper()
    dst = str(route.get("destination") or "").strip().upper()
    return f"{org}-{dst}" if (org and dst) else ""


def route_region(route: dict) -> str:
    region = str(route.get("region") or "").strip()
    if region:
        return region
    dest = str(route.get("destination") or "").strip().upper()
    return DEST_REGION.get(dest, dest)


def route_pax(route: dict) -> int:
    return int(route.get("pax") or 1)


def route_class(route: dict) -> str:
    return str(route.get("bookingClass") or "").strip().upper()


def route_fare_only(route: dict) -> bool:
    return bool(route.get("fareOnly", True))


def route_start_date(route: dict) -> str:
    return str(route.get("startDate") or "").strip()


def route_end_date(route: dict) -> str:
    return str(route.get("endDate") or "").strip()


def effective_start(route: dict, default_start: date) -> date:
    """노선별 조회시작일이 기준 시작일보다 늦으면 그 날짜부터 조회한다."""
    raw = route_start_date(route)
    if not raw:
        return default_start
    return max(default_start, date.fromisoformat(raw))


def effective_end(route: dict, main_end: date | None) -> date | None:
    """메인 종료일과 노선 조회종료일 중 더 빠른 날짜(교집합)를 반환한다."""
    raw = route_end_date(route)
    route_end = date.fromisoformat(raw) if raw else None
    if main_end and route_end:
        return min(main_end, route_end)
    return main_end or route_end


def plan_jobs(jobs: list[tuple[dict, int]], main_start: date,
              main_end: date | None) -> tuple[list[tuple[dict, int, date, date]], list[str]]:
    """선택된 노선별 실제 조회 구간(교집합)을 계산하고, 종료일 공란·기간 미중첩 사유를 분리해 반환한다."""
    valid: list[tuple[dict, int, date, date]] = []
    issues: list[str] = []
    for route, days in jobs:
        label = f"{route_group(route)} {route['depFlight']} +{days}"
        job_start = effective_start(route, main_start)
        job_end = effective_end(route, main_end)
        if job_end is None:
            issues.append(f"{label}: 종료일이 설정되지 않았습니다 (메인 종료일 또는 노선 조회종료일 필요)")
        elif job_start > job_end:
            issues.append(f"{label}: 실제 시작일({job_start})이 종료일({job_end})보다 늦습니다")
        else:
            valid.append((route, days, job_start, job_end))
    return valid, issues


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


def open_class(classes: dict, pax: int = 1) -> str | None:
    """좌석이 pax석 이상 남은 이코노미 클래스. Y 우선, 없으면 None(전석 마감)."""
    keys = list(classes.keys())
    if "Y" in classes:
        # Sabre는 객실 등급 순으로 나열하므로 Y부터 끝까지가 이코노미 객실이다.
        economy = {k: classes[k] for k in keys[keys.index("Y"):]}
    else:
        economy = {k: v for k, v in classes.items() if k not in PREMIUM}
    if economy.get("Y", 0) >= pax:
        return "Y"
    return next((k for k, v in economy.items() if v >= pax), None)


def sell_state(text: str, airline: str = "", number: int = 0, day: str = "", pax: int = 1) -> str:
    up = re.sub(r"\s+", " ", text.upper())
    if re.search(rf"\b(SS|HK|GK){pax}\b", up):
        if airline and not re.search(rf"\b{airline}\s*0*{number}[A-Z]?\b", up):
            return "error"
        if day and day not in up:
            return "error"
        return "ok"
    if re.search(r"\b(UC|UN|LL|HL|NO)\d+\b|UNABLE", up):
        return "sold"
    return "error"


def parse_wpncb(text: str, airline: str, origin: str, dest: str, out_no: int = 0, ret_no: int = 0,
                out_d: str = "", ret_d: str = "", *, pax: int = 1, fare_only: bool = True) -> int | str:
    up = re.sub(r"[ \t]+", " ", text.upper())
    if fare_only:
        # UI 표("1- KRW340000")와 API 원본("FARE KRW 364000") 모두 지원하며 TOTAL/TAX는 제외한다.
        fare = re.search(r"(?:\b\d+-|(?:^|\n)\s*FARE)\s*KRW\s*([\d,]+)", up)
    else:
        # 텍스 포함 전체금액: API 원본("TOTAL KRW 303200") 또는 UI 표("1- KRW... KRW... [XT] KRW596300")
        fare = (re.search(r"(?:^|\n)\s*TOTAL\s*KRW\s*([\d,]+)", up)
                or re.search(r"\b\d+-\s*KRW\s*[\d,]+\s+KRW\s*[\d,]+(?:\s+[A-Z0-9]{2})?\s+KRW\s*([\d,]+)", up))
    city = CITY.get(origin, origin)
    dest_city = CITY.get(dest, dest)
    out_leg = f"{city} {airline} {dest}" in up or f"{city} {airline} {dest_city}" in up
    ret_leg = f"{airline} {city}" in up or f"{airline} {origin}" in up
    # Sabre Red Web WPNCB 카드의 innerText는 여정 줄이 접혀 생략될 수 있어, 있을 때만 추가 대조한다.
    has_seg_lines = bool(re.search(rf"\b1 {airline} \d+[A-Z]? \d{{2}}[A-Z]{{3}}\b", up))
    segs_ok = True
    if has_seg_lines and out_no and ret_no:
        seg1 = re.search(rf"\b1 {airline} 0*{out_no} ?[A-Z]? {out_d}\b[^\n]*\b(SS|HK|GK){pax}\b", up)
        seg2 = re.search(rf"\b2 {airline} 0*{ret_no} ?[A-Z]? {ret_d}\b[^\n]*\b(SS|HK|GK){pax}\b", up)
        segs_ok = bool(seg1 and seg2)
    if fare and out_leg and ret_leg and segs_ok:
        return int(fare.group(1).replace(",", ""))
    if any(p in up for p in WPNCB_SOLD):
        return SOLD
    return ERR


def output_path(route: dict, days: int, today: date, root: Path | str | None = None) -> Path:
    name = f"{today:%Y%m%d} 조회_{route['origin']}{route['destination']}_{route['airline']}_플러스{days}.xlsx"
    base = Path(str(root).strip()) if str(root or "").strip() else OUTPUT_ROOT
    return base / route_region(route) / name


def group_summary_path(group: str, region: str, today: date, root: Path | str | None = None) -> Path:
    safe_group = re.sub(r'[\\/:*?"<>|]+', '-', group.strip()) or 'GROUP'
    base = Path(str(root).strip()) if str(root or '').strip() else OUTPUT_ROOT
    return base / region / f'{today:%Y%m%d} 조회_{safe_group}_최저가통합.xlsx'


def save_group_summary_workbook(path: Path, group: str, entries: list[tuple[dict, int, Path]]) -> Path:
    """한 노선그룹의 편명별 조회 엑셀을 모아 날짜별 최저가·최저가 항공 수식 시트로 저장한다."""
    if not entries:
        raise ValueError('통합할 조회 결과가 없습니다.')
    dep_counts: dict[str, int] = {}
    for route, _days, _p in entries:
        dep_counts[route['depFlight']] = dep_counts.get(route['depFlight'], 0) + 1
    col_labels: list[str] = []
    col_maps: list[dict[date, int | str]] = []
    all_dates: set[date] = set()
    for route, days, xlsx_path in entries:
        dep = route['depFlight']
        col_labels.append(f'{dep}(+{days})' if dep_counts[dep] > 1 else dep)
        per_date: dict[date, int | str] = {}
        wb_in = load_workbook(xlsx_path, read_only=True)
        try:
            ws_in = wb_in.active
            for row in ws_in.iter_rows(min_row=2, values_only=True):
                if not row or row[0] is None:
                    continue
                d_val = row[0].date() if hasattr(row[0], 'date') else date.fromisoformat(str(row[0]).strip())
                per_date[d_val] = row[1]
                all_dates.add(d_val)
        finally:
            wb_in.close()
        col_maps.append(per_date)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r'[:\\/?*\[\]]', '-', group.strip())[:31] or 'Sheet1'

    font_reg = Font(name='맑은 고딕', size=11)
    font_bold = Font(name='맑은 고딕', size=11, bold=True)
    align_c = Alignment(horizontal='center', vertical='center')
    fill_hdr = PatternFill(fill_type='solid', start_color='FFC9DAF8', end_color='FFC9DAF8')
    fill_sold = PatternFill(fill_type='solid', start_color='FFFCE4D6', end_color='FFFCE4D6')

    n_cols = len(col_labels)
    last_flight_col = 1 + n_cols
    last_letter = get_column_letter(last_flight_col)
    date_col = last_flight_col + 2
    min_col = last_flight_col + 3
    air_col = last_flight_col + 4
    min_letter = get_column_letter(min_col)

    for idx, label in enumerate(col_labels, start=2):
        cell = ws.cell(2, idx, label)
        cell.font, cell.alignment = font_bold, align_c
    for col_idx, label in ((date_col, '날짜'), (min_col, '최저가'), (air_col, '최저가 항공')):
        cell = ws.cell(2, col_idx, label)
        cell.font, cell.alignment, cell.fill = font_bold, align_c, fill_hdr

    for r_idx, d in enumerate(sorted(all_dates), start=3):
        c_date = ws.cell(r_idx, 1, d)
        c_date.font, c_date.alignment, c_date.number_format = font_reg, align_c, 'yyyy-mm-dd'
        for offset, per_date in enumerate(col_maps):
            val = per_date.get(d)
            cell = ws.cell(r_idx, 2 + offset, val)
            cell.font, cell.alignment = font_reg, align_c
            if isinstance(val, int):
                cell.number_format = '#,##0'
            elif val == SOLD:
                cell.fill = fill_sold
        sc_date = ws.cell(r_idx, date_col, f'=A{r_idx}')
        sc_date.font, sc_date.alignment, sc_date.number_format = font_reg, align_c, 'yyyy-mm-dd'
        sc_min = ws.cell(r_idx, min_col, f'=IF(COUNT(B{r_idx}:{last_letter}{r_idx})=0,"{SOLD}",MIN(B{r_idx}:{last_letter}{r_idx}))')
        sc_min.font, sc_min.alignment, sc_min.number_format = font_reg, align_c, '#,##0'
        sc_air = ws.cell(
            r_idx,
            air_col,
            f'=IF(ISNUMBER({min_letter}{r_idx}),IFERROR(INDEX($B$2:${last_letter}$2,1,MATCH({min_letter}{r_idx},B{r_idx}:{last_letter}{r_idx},0)),""),"")',
        )
        sc_air.font, sc_air.alignment = font_reg, align_c

    ws.column_dimensions['A'].width = 13
    for idx in range(2, last_flight_col + 1):
        ws.column_dimensions[get_column_letter(idx)].width = 12
    ws.column_dimensions[get_column_letter(last_flight_col + 1)].width = 4
    ws.column_dimensions[get_column_letter(date_col)].width = 13
    ws.column_dimensions[get_column_letter(min_col)].width = 12
    ws.column_dimensions[get_column_letter(air_col)].width = 14
    wb.save(path)
    return path


def basis_text(route: dict, days: int) -> str:
    region = route_region(route)
    dest = "충칭" if region == "중경" else region
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
    wb = load_workbook(path, read_only=True)
    try:
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        c1 = ws["C1"].value
    finally:
        wb.close()
    expected = [(start + timedelta(n)).isoformat() for n in range((end - start).days + 1)]
    if c1 != basis:
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


CSV_COLUMNS = (
    ("노선그룹", "routeGroup"),
    ("출발지", "origin"),
    ("도착지", "destination"),
    ("항공사", "airline"),
    ("출국편", "depFlight"),
    ("귀국편", "retFlight"),
    ("항공일수", "days"),
    ("조회시작일", "startDate"),
    ("조회종료일", "endDate"),
    ("조회인원", "pax"),
    ("조회클래스", "bookingClass"),
    ("운임기준", "fareOnly"),
    ("사용", "enabled"),
)
_CSV_ALIASES = {
    **{ko: key for ko, key in CSV_COLUMNS},
    **{key: key for _, key in CSV_COLUMNS},
    "항공일수(+N)": "days",
    "운임만": "fareOnly",
    "지역명": "region",
    "region": "region",
}


def _parse_csv_bool(value: str | None, *, default: bool, false_tokens: tuple[str, ...]) -> bool:
    text = str(value or "").strip().upper()
    if not text:
        return default
    return text not in false_tokens


def _normalize_csv_date(value: str | None) -> str:
    text = str(value or "").strip()
    m = re.fullmatch(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else text


def export_routes_csv(path: Path, routes: list[dict]) -> None:
    """엑셀에서 한글이 깨지지 않도록 UTF-8 BOM CSV로 노선 목록을 내보낸다."""
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([ko for ko, _ in CSV_COLUMNS])
        for r in routes:
            w.writerow([
                route_group(r),
                r["origin"],
                r["destination"],
                r["airline"],
                r["depFlight"],
                r["retFlight"],
                ",".join(map(str, r["days"])),
                route_start_date(r),
                r["endDate"],
                route_pax(r),
                route_class(r),
                "FARE KRW" if route_fare_only(r) else "TOTAL KRW",
                "사용" if r.get("enabled", True) else "중지",
            ])


def import_routes_csv(path: Path) -> list[dict]:
    """UTF-8(BOM)/UTF-16/CP949 및 쉼표·탭 구분 CSV를 읽어 검증된 노선 목록으로 변환한다."""
    raw_bytes = path.read_bytes()
    text = None
    encs = ("utf-16", "utf-8-sig", "cp949") if raw_bytes[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp949", "utf-16")
    for enc in encs:
        try:
            text = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("CSV 인코딩을 읽지 못했습니다. UTF-8 또는 CP949로 저장해 주세요.")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("CSV 파일이 비어 있습니다.")
    first = lines[0]
    delim = "\t" if "\t" in first else (";" if ";" in first and "," not in first else ",")
    rows = list(csv.reader(lines, delimiter=delim))
    headers = [_CSV_ALIASES.get(h.strip(), "") for h in rows[0]]
    if not any(headers):
        raise ValueError("CSV 첫 줄 헤더를 인식할 수 없습니다. 먼저 [CSV 내보내기] 양식을 확인하세요.")
    routes: list[dict] = []
    for line_no, cols in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in cols):
            continue
        raw = {headers[i]: cols[i].strip() for i in range(min(len(headers), len(cols))) if headers[i]}
        raw["startDate"] = _normalize_csv_date(raw.get("startDate"))
        raw["endDate"] = _normalize_csv_date(raw.get("endDate"))
        raw["fareOnly"] = _parse_csv_bool(
            raw.get("fareOnly"),
            default=True,
            false_tokens=("TOTAL KRW", "TOTAL", "총액", "총액(텍스포함)", "FALSE", "0", "N", "NO", "해제"),
        )
        raw["enabled"] = _parse_csv_bool(
            raw.get("enabled"),
            default=True,
            false_tokens=("중지", "미사용", "FALSE", "0", "N", "NO"),
        )
        try:
            routes.append(normalize_route(raw))
        except ValueError as exc:
            raise ValueError(f"{line_no}행 오류: {exc}") from exc
    if not routes:
        raise ValueError("불러올 노선 데이터가 없습니다.")
    return routes


def is_complete_route(route: dict) -> bool:
    keys = ("origin", "destination", "airline", "depFlight", "retFlight")
    if not all(str(route.get(k) or "").strip() for k in keys):
        return False
    if not route.get("days"):
        return False
    for k in ("startDate", "endDate"):
        val = str(route.get(k) or "").strip()
        if val:
            try:
                date.fromisoformat(val)
            except ValueError:
                return False
    return True


def normalize_route(form: dict, *, allow_partial: bool = False) -> dict:
    days = sorted({int(x) for x in re.findall(r"\d+", str(form.get("days", "")))})
    req_keys = ("origin", "destination", "airline", "depFlight", "retFlight")
    route = {k: str(form.get(k, "")).strip() for k in req_keys}
    for k in ("origin", "destination", "airline", "depFlight", "retFlight"):
        route[k] = route[k].upper()
    if not allow_partial and (not all(route.values()) or not days):
        raise ValueError("모든 칸을 입력하세요. 항공일수는 2,3 처럼 쉼표로 여러 개 입력합니다.")
    start_date = str(form.get("startDate") or "").strip()
    if start_date:
        date.fromisoformat(start_date)
    end_date = str(form.get("endDate") or "").strip()
    if end_date:
        date.fromisoformat(end_date)
    pax_raw = str(form.get("pax", "1")).strip() or "1"
    if not pax_raw.isdigit() or not (1 <= int(pax_raw) <= 9):
        raise ValueError("조회인원은 1~9 사이의 숫자로 입력하세요.")
    pax = int(pax_raw)
    raw_cls = str(form.get("bookingClass") or "").strip()
    booking_class = "" if raw_cls in ("최저가", "자동") else raw_cls.upper()
    if booking_class and not re.fullmatch(r"[A-Z]", booking_class):
        raise ValueError("조회클래스는 영문 1글자(예: Y, M, Q) 또는 빈칸으로 입력하세요.")
    group = route_group({**route, "routeGroup": form.get("routeGroup", "")})
    region = str(form.get("region") or "").strip() or DEST_REGION.get(route["destination"], route["destination"])
    return {
        "routeGroup": group,
        "region": region,
        **route,
        "startDate": start_date,
        "endDate": end_date,
        "days": days,
        "pax": pax,
        "bookingClass": booking_class,
        "fareOnly": bool(form.get("fareOnly", True)),
        "enabled": bool(form.get("enabled", True)),
    }


def group_routes(routes: list[dict]) -> dict[str, list[dict]]:
    """사용 중이면서 모든 필수 항목이 채워진 노선만 노선그룹 단위로 묶어 반환한다."""
    grouped: dict[str, list[dict]] = {}
    for r in routes:
        if not r.get("enabled", True) or not is_complete_route(r):
            continue
        grouped.setdefault(route_group(r), []).append(r)
    return grouped

