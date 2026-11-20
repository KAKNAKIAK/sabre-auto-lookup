"""실제 Sabre 화면 텍스트(2026-11-19 에고 라이트 실측)로 판정 로직을 점검한다."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

import sabre_core as c
import sabre_cli as cli
import sabre_app as app_mod
import sabre_terminal as t

AVAIL_OUT = """101DECICNCKG¥CA
01DEC TUE ICN/Z¥9 CKG/-1
1
CA
440
J6
C6
Y9
B9
M9
ICN
CKG
14:00
16:55
738
0
3H 55MIN
2
CA/OZ
5002
J0
C0
M0
ICN
PEK
08:20
09:45
3
CA
4138
J8
Y9
CKG
13:00"""

SOLD_OUT = """20NOV FRI ICN/Z¥9 CKG/-1
1
CA
440
J0
C0
D0
Y0
B0
M0
K0
ICN
CKG
14:00"""

WPNCB_OK = """WPNCB
BASE FARE TAXES/FEES/CHARGES
1- KRW340000 KRW256300 XT KRW596300 ADT
ADT - 1 TRCPKR SLRCKR
SEL CA CKG119.19CA SEL134.09NUC253.28END ROE1342.36847
VALIDATING CARRIER - CA
1 CA 440T 01DEC 2 ICNCKG SS1 1400 1655 /DCCA /E
2 CA 439S 04DEC 5 CKGICN SS1 0830 1300 /DCCA /E"""


class CoreTest(unittest.TestCase):
    def test_date_and_flight(self):
        self.assertEqual(c.ddmmm(date(2026, 12, 1)), "01DEC")
        self.assertEqual(c.flight_no("CA 440", "CA"), 440)
        self.assertEqual(c.flight_no("VJ979", "VJ"), 979)
        self.assertEqual(c.flight_no("7C2217", "7C"), 2217)

    def test_availability_open(self):
        rows = c.parse_availability(AVAIL_OUT)
        row = c.find_row(rows, "CA", 440)
        self.assertEqual(row["line"], 1)
        self.assertEqual(c.open_class(row["classes"]), "Y")
        self.assertIsNone(c.find_row(rows, "CA", 5002))  # 공동운항 CA/OZ는 지정편이 아님
        self.assertEqual(c.find_row(rows, "CA", 4138)["line"], 3)

    def test_availability_sold_out(self):
        row = c.find_row(c.parse_availability(SOLD_OUT), "CA", 440)
        self.assertIsNone(c.open_class(row["classes"]))

    def test_availability_concatenated_innertext(self):
        glued = "5 KE/MU\n5843\nJCCCYCBCMCSCHCECKCLCUC\nICN\nTAO\n9 KE\n2081\nJ6C6D6I6RLZ5Y9B9M9S9H9E9K9L9U9Q9T9GC\nTAO"
        rows = c.parse_availability(glued)
        row = c.find_row(rows, "KE", 2081)
        self.assertEqual(row["line"], 9)
        self.assertEqual(row["classes"]["Y"], 9)
        self.assertEqual(row["classes"]["G"], 0)
        self.assertEqual(c.open_class(row["classes"]), "Y")

    def test_availability_raw_api_host_text(self):
        raw = (
            " 21NOV  SAT   ICN/Z¥9     CKG/-1\n"
            " 1CA     440 J3 C3 D3 Z0 ICNCKG 1400 1655 738 M 0 DCA /E\n"
            "             R0 Y9 B9 M9 U9 H9 Q9 V9 W0 S0 T0 L0 P0 N0 K0\n"
            " 2CA/OZ 5002 J0 C0 M0 U0 ICNPEK 0820 0945 32Q 0 X357 DCA /E\n"
            "107C    2217 Y4 B4 M0    ICNDAD 2030 2330 738   0 DCA /E\n"
            "11CA    1439 J8 C5 D3 Z2    CKG 1400 1655 738 S 0 24 DCA /E\n"
            "             R1 Y9 B9 M9 U9 H9 Q9 V9 W9 S9 T2 L9 P9 N0 K9.\n"
        )
        rows = c.parse_availability(raw)
        ca440 = c.find_row(rows, "CA", 440)
        self.assertEqual(ca440["line"], 1)
        self.assertEqual(ca440["classes"]["Y"], 9)
        self.assertEqual(ca440["classes"]["J"], 3)
        self.assertEqual(c.open_class(ca440["classes"]), "Y")
        self.assertIsNone(c.find_row(rows, "CA", 5002))
        jc = c.find_row(rows, "7C", 2217)
        self.assertEqual(jc["line"], 10)
        self.assertEqual(c.open_class(jc["classes"]), "Y")
        # 마지막 줄 끝에 마침표(.)가 붙어도 2번째 클래스 줄을 놓치지 않아야 한다.
        ca1439 = c.find_row(rows, "CA", 1439)
        self.assertEqual(ca1439["line"], 11)
        self.assertEqual(ca1439["classes"]["Y"], 9)
        self.assertEqual(ca1439["classes"]["K"], 9)
        self.assertEqual(c.open_class(ca1439["classes"]), "Y")

    def test_open_class_skips_business(self):
        self.assertEqual(c.open_class({"J": 9, "Y": 0, "M": 3}), "M")
        # Y 앞의 프리미엄/비즈니스/퍼스트(P4, G9, E1)는 좌석이 있어도 이코노미 마감으로 본다
        self.assertIsNone(c.open_class({"P": 4, "J": 9, "G": 9, "E": 1, "Y": 0, "B": 0, "M": 0}))
        # Y 뒤의 P는 이코노미 특가(예: CA)로 취급한다
        self.assertEqual(c.open_class({"J": 0, "Y": 0, "B": 0, "P": 5, "K": 0}), "P")

    def test_sell_state(self):
        self.assertEqual(c.sell_state("1 CA\n440\nY\n01DEC TUE\nICN CKG\nSS1\n14:00", "CA", 440, "01DEC"), "ok")
        self.assertEqual(c.sell_state("1 CA 440Y   01DEC 2 ICNCKG SS1  1400  1655  /DCCA /E", "CA", 440, "01DEC"), "ok")
        self.assertEqual(c.sell_state("1 CA\n442\nY\n01DEC TUE\nICN CKG\nSS1", "CA", 440, "01DEC"), "error")
        self.assertEqual(c.sell_state("1 CA 440 Y 20NOV ICN CKG UC1"), "sold")
        self.assertEqual(c.sell_state("DUPLICATE SEGMENT - NOT ALLOWED."), "error")

    def test_wpncb(self):
        args = ("CA", "ICN", "CKG", 440, 439, "01DEC", "04DEC")
        self.assertEqual(c.parse_wpncb(WPNCB_OK, *args), 340000)
        # 실제 Chrome innerText처럼 여정 줄이 접힌 WPNCB 카드도 왕복 계산식과 기본운임으로 파싱
        collapsed = "WPNCB\n\tBASE FARE\tTAXES\n1-\tKRW340000\tKRW255400\tXT\tKRW595400\tADT\nSEL CA CKG119.19CA SEL134.09NUC253.28END"
        self.assertEqual(c.parse_wpncb(collapsed, *args), 340000)
        raw_api = (
            "FARE  KRW    364000  \n"
            "TAX   KRW     24000BP KRW     18000CN KRW    213400YQ\n"
            "TOTAL KRW    619400\n"
            " SEL CA CKG119.19CA SEL151.97NUC271.16END ROE1342.36847\n"
            " 1 CA 440T 01DEC 2 ICNCKG SS1  1400  1655  /DCCA /E\n"
            " 2 CA 439W 04DEC 5 CKGICN SS1  0830  1300  /DCCA /E\n"
        )
        self.assertEqual(c.parse_wpncb(raw_api, *args), 364000)
        self.assertEqual(c.parse_wpncb(raw_api.replace("439W", "441W"), *args), c.ERR)
        self.assertEqual(c.parse_wpncb("¥CODE - UC SEG STATUS NOT ALLOWED-0003¥.", *args), c.SOLD)
        self.assertEqual(c.parse_wpncb("NCB RESTRICTED ON WAILISTED SEGS-USE SEGMENT SELECT.", *args), c.SOLD)
        self.assertEqual(c.parse_wpncb("¥FORMAT¥.", *args), c.ERR)
        # 다른 귀국편으로 운임이 나오면 쓰지 않는다
        self.assertEqual(c.parse_wpncb(WPNCB_OK.replace("439S", "441S"), *args), c.ERR)
        # 텍스 포함 전체금액(fare_only=False)은 UI/API 모두 TOTAL 금액을 추출한다
        self.assertEqual(c.parse_wpncb(WPNCB_OK, *args, fare_only=False), 596300)
        self.assertEqual(c.parse_wpncb(collapsed, *args, fare_only=False), 595400)
        self.assertEqual(c.parse_wpncb(raw_api, *args, fare_only=False), 619400)
        # 다인 조회(pax=2)는 SS2 세그를 검증한다
        raw_2pax = raw_api.replace("SS1", "SS2")
        self.assertEqual(c.parse_wpncb(raw_2pax, *args, pax=2, fare_only=True), 364000)
        self.assertEqual(c.parse_wpncb(raw_2pax, *args, pax=2, fare_only=False), 619400)
        self.assertEqual(c.parse_wpncb(raw_api, *args, pax=2, fare_only=True), c.ERR)

    def test_pax_class_and_total_fare_query_once(self):
        self.assertEqual(c.open_class({"J": 9, "Y": 2, "B": 5}, pax=4), "B")
        self.assertIsNone(c.open_class({"J": 9, "Y": 2, "B": 3}, pax=4))
        self.assertEqual(c.sell_state(" 1 KE 843M 01DEC 2 ICNTAO SS2 1255 1340", "KE", 843, "01DEC", pax=2), "ok")
        self.assertEqual(c.sell_state(" 1 KE 843M 01DEC 2 ICNTAO SS1 1255 1340", "KE", 843, "01DEC", pax=2), "error")
        self.assertEqual(c.sell_state(" 1 KE 843M 01DEC 2 ICNTAO UC2", "KE", 843, "01DEC", pax=2), "sold")

        sent = []
        class FakeTerm:
            def cmd(self, text, settle=0.25):
                sent.append(text)
                if text == "I":
                    return "IGD"
                if text.startswith("101DEC"):
                    return " 01DEC TUE ICN/Z¥9 TAO/-1\n 1KE 843 J4 Y9 M3 K1 ICNTAO 1255 1340\n"
                if text.startswith("103DEC"):
                    return " 03DEC THU TAO/Z¥8 ICN/¥1\n 1KE 844 J4 Y9 M2 K1 TAOICN 1455 1735\n"
                if text == "02M1":
                    return " 1 KE 843M 01DEC 2 ICNTAO SS2" if sent.count("02M1") == 1 else " 2 KE 844M 03DEC 4 TAOICN SS2"
                if text == "WPNCB":
                    return (
                        "FARE  KRW    210000\n"
                        "TAX   KRW    153200\n"
                        "TOTAL KRW    363200\n"
                        " SEL KE TAO78.22KE SEL78.22NUC156.44END\n"
                        " 1 KE 843M 01DEC 2 ICNTAO SS2  1255  1340  /DCKE /E\n"
                        " 2 KE 844M 03DEC 4 TAOICN SS2  1455  1735  /DCKE /E\n"
                    )
                return ""

        route = {"airline": "KE", "origin": "ICN", "destination": "TAO", "depFlight": "KE843", "retFlight": "KE844",
                 "pax": 2, "bookingClass": "M", "fareOnly": False}
        total = t.query_once(FakeTerm(), route, 2, date(2026, 12, 1), 0.1)
        self.assertEqual(total, 363200)
        self.assertIn("02M1", sent)
        self.assertIn("WPNCB", sent)
        self.assertNotIn("WP", sent)
        # 요청 클래스 잔여석 부족 시 세그 판매 없이 즉시 예약마감
        sold_route = {**route, "bookingClass": "K"}
        sent.clear()
        self.assertEqual(t.query_once(FakeTerm(), sold_route, 2, date(2026, 12, 1), 0.1), c.SOLD)
        self.assertNotIn("02K1", sent)

    def test_long_sell_fast_path_and_adaptive_fallback(self):
        sent = []
        class FastTerm:
            long_sell = True
            _ls_fallbacks = 0
            def cmd(self, text, settle=0.25):
                sent.append(text)
                if text == "I":
                    return "IGD"
                if "§" in text:
                    return " 1455 1735 4 M SEG 2 SS Y /DCKE /E"
                if text == "WPNCB":
                    return (
                        "FARE  KRW    180000\n"
                        "TOTAL KRW    333200\n"
                        " SEL KE TAO55.87KE SEL55.87NUC111.74END\n"
                        " 1 KE 843T 01DEC 2 ICNTAO SS1  1255  1340  /DCKE /E\n"
                        " 2 KE 844T 03DEC 4 TAOICN SS1  1455  1735  /DCKE /E\n"
                    )
                return ""
        route = {"airline": "KE", "origin": "ICN", "destination": "TAO", "depFlight": "KE843", "retFlight": "KE844"}
        fare = t.query_once(FastTerm(), route, 2, date(2026, 12, 1), 0.1)
        self.assertEqual(fare, 180000)
        self.assertEqual(sent, ["I", "0KE843Y01DECICNTAONN1§0KE844Y03DECTAOICNNN1", "WPNCB"])

        # Long Sell이 UC를 반환하지만 Short Sell이 연속 2회 성공하면 이후 Long Sell 자동 비활성화
        sent2 = []
        class RejectLongSellTerm:
            long_sell = True
            _ls_fallbacks = 0
            def cmd(self, text, settle=0.25):
                sent2.append(text)
                if text == "I":
                    return "IGD"
                if "§" in text:
                    return " 1455 1735 4 M SEG 2 UC M /DCKE"
                if text.startswith("101DEC") or text.startswith("102DEC"):
                    return f" {text[1:6]} TUE ICN/Z¥9 TAO/-1\n 1KE 843 Y9 M9 ICNTAO 1255 1340\n"
                if text.startswith("103DEC") or text.startswith("104DEC"):
                    return f" {text[1:6]} THU TAO/Z¥8 ICN/¥1\n 1KE 844 Y9 M9 TAOICN 1455 1735\n"
                if text == "02M1":
                    return " 1 KE 843M 01DEC 2 ICNTAO SS2" if sent2.count("02M1") % 2 == 1 else " 2 KE 844M 03DEC 4 TAOICN SS2"
                if text == "WPNCB":
                    return "FARE  KRW    210000\n SEL KE TAO78.22KE SEL78.22NUC156.44END\n"
                return ""
        term2 = RejectLongSellTerm()
        m_route = {**route, "pax": 2, "bookingClass": "M"}
        self.assertEqual(t.query_once(term2, m_route, 2, date(2026, 12, 1), 0.1), 210000)
        self.assertTrue(term2.long_sell)
        self.assertEqual(t.query_once(term2, m_route, 2, date(2026, 12, 1), 0.1), 210000)
        self.assertFalse(term2.long_sell)
        sent2.clear()
        self.assertEqual(t.query_once(term2, m_route, 2, date(2026, 12, 1), 0.1), 210000)
        self.assertFalse(any("§" in cmd for cmd in sent2))

    def test_find_target_host_not_query(self):
        fake = [
            {"type": "page", "url": t.LOGIN_URL},
        ]
        orig = t.targets
        t.targets = lambda: fake
        try:
            self.assertIsNone(t.find_target("srw.sabre.com"))
            self.assertIsNotNone(t.find_target("accounts.havail.sabre.com"))
        finally:
            t.targets = orig

    def test_launch_and_login_waits_for_srw_boot_without_navigating_away(self):
        import threading
        navigated, connect_calls, logs = [], 0, []
        class FakePage:
            def __init__(self, target):
                self.target = target
            def eval(self, expr):
                if expr == t.SESSION_EXPIRED_JS:
                    return False
                if expr == t.S02_MODAL_JS:
                    return ""
                if expr == t.FOCUS_JS:
                    return True
                return None
            def send(self, method, params=None):
                if method == "Page.navigate":
                    navigated.append(params)
                return {}
            def close(self):
                pass
        class FakeTerm:
            def close(self):
                pass
        def fake_connect(cls=None, prefer_api=True):
            nonlocal connect_calls
            connect_calls += 1
            if connect_calls < 3:
                raise t.SessionExpired("아직 호스트 초기화 중")
            return FakeTerm()
        orig_find, orig_page, orig_conn, orig_sleep = t.find_target, t.Page, t.Terminal.connect, t.time.sleep
        t.find_target = lambda host: {"url": "https://srw.sabre.com/26.9.9/"} if host == "srw.sabre.com" else None
        t.Page = FakePage
        t.Terminal.connect = classmethod(fake_connect)
        t.time.sleep = lambda _s: None
        try:
            ok = t.launch_and_login({}, logs.append, threading.Event(), push_resend_interval=10.0, max_push_resends=1)
            self.assertTrue(ok)
            self.assertEqual(navigated, [])  # 부팅 중인 정상 Sabre 탭에서 로그인 URL로 강제 이탈하지 않아야 함
            self.assertEqual(connect_calls, 3)
        finally:
            t.find_target, t.Page, t.Terminal.connect, t.time.sleep = orig_find, orig_page, orig_conn, orig_sleep

    def test_find_flight_paginates_with_1star(self):
        page1 = "01DEC TUE ICN/Z¥9 SGN/-2\n1 KE 475 J9 Y9 B9 ICN SGN 08:00"
        page2 = "7 KE 471 J9 Y9 B9 ICN SGN 18:30"
        sent = []
        class FakeTerm:
            def cmd(self, text, settle=0.4):
                sent.append(text)
                return page1 if text != "1*" else page2
        row = t.find_flight(FakeTerm(), "101DECICNSGN¥KE", "KE", 471, "01DEC", 0.1)
        self.assertEqual(sent, ["101DECICNSGN¥KE", "1*"])
        self.assertEqual(row["line"], 7)

    def test_wp_fallback_not_triggered_when_api_fare_present(self):
        sent = []
        class FakeTerm:
            def cmd(self, text, settle=0.25):
                sent.append(text)
                if text == "I":
                    return "IGD"
                if text.startswith("101DEC"):
                    return " 01DEC TUE ICN/Z¥9 CKG/-1\n 1CA 440 J6 Y9 ICNCKG 1400 1655\n"
                if text.startswith("104DEC"):
                    return " 04DEC FRI CKG/Z¥8 ICN/¥1\n 1CA 439 J3 Y9 CKGICN 0830 1300\n"
                if text.startswith("01Y"):
                    return " 1 CA 440Y 01DEC 2 ICNCKG SS1" if sent.count(text) == 1 else " 2 CA 439Y 04DEC 5 CKGICN SS1"
                if text == "WPNCB":
                    return (
                        "NO LOWER FARE - CURRENT FARE KEPT\n"
                        "FARE  KRW    364000\n"
                        " SEL CA CKG119.19CA SEL151.97NUC271.16END\n"
                        " 1 CA 440T 01DEC 2 ICNCKG SS1\n"
                        " 2 CA 439W 04DEC 5 CKGICN SS1\n"
                    )
                return ""
        route = {"airline": "CA", "origin": "ICN", "destination": "CKG", "depFlight": "CA440", "retFlight": "CA439"}
        fare = t.query_once(FakeTerm(), route, 3, date(2026, 12, 1), 0.1)
        self.assertEqual(fare, 364000)
        self.assertNotIn("WP", sent)

    def test_launch_and_login_resends_okta_push_up_to_limit(self):
        import threading
        logs, clicks = [], 0
        class FakePage:
            def __init__(self, target):
                self.target = target
            def eval(self, expr):
                nonlocal clicks
                if expr == t.PUSH_JS:
                    clicks += 1
                    return True
                if 'input[name="userId"]' in expr:
                    return False
                return ""
            def send(self, method, params=None):
                return {}
            def close(self):
                pass
        orig_find, orig_page, orig_sleep = t.find_target, t.Page, t.time.sleep
        t.find_target = lambda host: {"url": t.LOGIN_URL} if host == "accounts.havail.sabre.com" else None
        t.Page = FakePage
        t.time.sleep = lambda _s: None
        try:
            ok = t.launch_and_login({}, logs.append, threading.Event(),
                                    push_resend_interval=0.0, max_push_resends=5)
            self.assertFalse(ok)
            self.assertEqual(clicks, 6)  # 최초 1회 + 자동 재전송 5회
            self.assertTrue(any("5회 모두 미승인" in m for m in logs))
        finally:
            t.find_target, t.Page, t.time.sleep = orig_find, orig_page, orig_sleep

    def test_run_job_auto_relogins_and_resumes_interrupted_date(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            orig_root, orig_conn, orig_login, orig_qd = c.OUTPUT_ROOT, t.Terminal.connect, t.launch_and_login, t.query_date
            c.OUTPUT_ROOT = Path(tmp)
            relogins, attempts = 0, {}
            class FakeTerm:
                mode = "API"
                def minimize(self): pass
                def cmd(self, _txt): return "IGD"
                def close(self): pass
            def fake_connect(cls=None, prefer_api=True):
                return FakeTerm()
            def fake_login(cfg, log, stop, force_relogin=False, **_kw):
                nonlocal relogins
                relogins += 1
                return True
            def fake_qd(term, route, days, dep):
                attempts[dep] = attempts.get(dep, 0) + 1
                if dep == date(2026, 12, 2) and attempts[dep] == 1:
                    raise t.SessionExpired("expired mid-loop")
                return 340000 if dep == date(2026, 12, 1) else 364000
            t.Terminal.connect = classmethod(fake_connect)
            t.launch_and_login = fake_login
            t.query_date = fake_qd
            try:
                route = {"region": "중경", "origin": "ICN", "destination": "CKG", "airline": "CA",
                         "depFlight": "CA440", "retFlight": "CA439"}
                out = t.run_job(route, 3, date(2026, 12, 1), date(2026, 12, 2), date(2026, 11, 20),
                                lambda *_a: None, threading.Event(), background=False, cfg={"agentId": "x"})
                self.assertIsNotNone(out)
                self.assertEqual(relogins, 1)
                self.assertEqual(attempts[date(2026, 12, 2)], 2)
                ws = c.load_workbook(out).active
                rows = [(r[0], r[1]) for r in ws.iter_rows(min_row=2, values_only=True)]
                self.assertEqual(rows, [("2026-12-01", 340000), ("2026-12-02", 364000)])
            finally:
                c.OUTPUT_ROOT, t.Terminal.connect, t.launch_and_login, t.query_date = orig_root, orig_conn, orig_login, orig_qd

    def test_names(self):
        route = {"region": "푸꾸옥", "origin": "ICN", "destination": "PQC", "airline": "VJ"}
        self.assertEqual(c.output_path(route, 3, date(2026, 11, 19)).name, "20261119 조회_ICNPQC_VJ_플러스3.xlsx")
        self.assertEqual(c.basis_text({**route, "region": "중경", "airline": "CA"}, 3), "인천/충칭 CA *+ 3 조회기준")

    def test_route_and_workbook(self):
        self.assertNotIn("region", [k for _, k in app_mod.FIELDS])
        r = c.normalize_route({"origin": "icn", "destination": "tao", "airline": "ke",
                               "depFlight": "ke 843", "retFlight": "KE844", "days": "3, 2", "endDate": "2027-10-31"})
        self.assertEqual(r["days"], [2, 3])
        self.assertEqual(r["routeGroup"], "ICN-TAO")
        self.assertEqual(r["region"], "칭다오")
        r_new = c.normalize_route({"origin": "ICN", "destination": "bkk", "airline": "KE",
                                   "depFlight": "KE651", "retFlight": "KE652", "days": "3", "endDate": "2027-10-31"})
        self.assertEqual(r_new["region"], "BKK")
        self.assertEqual((r_new["pax"], r_new["bookingClass"], r_new["fareOnly"]), (1, "", True))
        r_opt = c.normalize_route({"origin": "ICN", "destination": "TAO", "airline": "KE",
                                   "depFlight": "KE843", "retFlight": "KE844", "days": "2", "endDate": "2027-10-31",
                                   "pax": "4", "bookingClass": "j", "fareOnly": False})
        self.assertEqual((r_opt["pax"], r_opt["bookingClass"], r_opt["fareOnly"]), (4, "J", False))
        with self.assertRaises(ValueError):
            c.normalize_route({"origin": "ICN", "destination": "TAO", "airline": "KE",
                               "depFlight": "KE843", "retFlight": "KE844", "days": "2", "endDate": "2027-10-31", "pax": "0"})
        with self.assertRaises(ValueError):
            c.normalize_route({"origin": "ICN", "destination": "TAO", "airline": "KE",
                               "depFlight": "KE843", "retFlight": "KE844", "days": "2", "endDate": "2027-10-31", "bookingClass": "YM"})
        r2 = c.normalize_route({"routeGroup": "icn-dad_pm", "region": "다낭", "origin": "ICN", "destination": "DAD",
                                "airline": "KE", "depFlight": "KE457", "retFlight": "KE458", "days": "3", "endDate": "2027-10-31"})
        self.assertEqual(r2["routeGroup"], "ICN-DAD_PM")
        grouped = c.group_routes([r, r2, {**r2, "enabled": False}])
        self.assertEqual(list(grouped.keys()), ["ICN-TAO", "ICN-DAD_PM"])
        self.assertEqual(len(grouped["ICN-DAD_PM"]), 1)
        with self.assertRaises(ValueError):
            c.normalize_route({"region": "x", "days": ""})

    def test_routes_csv_export_and_import(self):
        routes = [
            c.normalize_route({"origin": "ICN", "destination": "TAO", "airline": "KE", "depFlight": "KE843",
                               "retFlight": "KE844", "days": "2,3", "endDate": "2027-10-31", "pax": 1, "bookingClass": "", "fareOnly": True}),
            c.normalize_route({"routeGroup": "ICN-DAD_S", "origin": "ICN", "destination": "DAD", "airline": "KE", "depFlight": "KE457",
                               "retFlight": "KE458", "days": "3", "endDate": "2027-10-31", "pax": 4, "bookingClass": "S", "fareOnly": False, "enabled": False}),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "routes.csv"
            c.export_routes_csv(csv_path, routes)
            self.assertTrue(csv_path.read_bytes().startswith(b"\xef\xbb\xbf"))  # UTF-8 BOM
            loaded = c.import_routes_csv(csv_path)
            self.assertEqual(loaded, routes)

            # CP949 인코딩 + 엑셀 슬래시 날짜 + '최저가' 표기 불러오기 지원
            cp949_path = Path(tmp) / "cp949.csv"
            cp949_path.write_text(
                "노선그룹,출발지,도착지,항공사,출국편,귀국편,항공일수,조회종료일,조회인원,조회클래스,운임기준,사용\n"
                'ICN-TAO,ICN,TAO,KE,KE843,KE844,"2,3",2027/10/5,2,최저가,TOTAL KRW,사용\n',
                encoding="cp949",
            )
            loaded2 = c.import_routes_csv(cp949_path)
            self.assertEqual(len(loaded2), 1)
            self.assertEqual((loaded2[0]["days"], loaded2[0]["endDate"], loaded2[0]["pax"], loaded2[0]["bookingClass"], loaded2[0]["fareOnly"]),
                             ([2, 3], "2027-10-05", 2, "", False))

            # CP949 + 탭(\t) 구분 CSV 불러오기 지원
            tsv_path = Path(tmp) / "tab.csv"
            tsv_path.write_text(
                "노선그룹\t출발지\t도착지\t항공사\t출국편\t귀국편\t항공일수\t조회종료일\t조회인원\t조회클래스\t운임기준\t사용\n"
                "ICN-CKG\tICN\tCKG\tCA\tCA440\tCA439\t3\t2027-10-31\t4\tY\tFARE KRW\t사용\n",
                encoding="cp949",
            )
            loaded_tsv = c.import_routes_csv(tsv_path)
            self.assertEqual(len(loaded_tsv), 1)
            self.assertEqual((loaded_tsv[0]["routeGroup"], loaded_tsv[0]["pax"], loaded_tsv[0]["bookingClass"]), ("ICN-CKG", 4, "Y"))

            # 잘못된 행은 행 번호와 함께 ValueError 발생
            bad_path = Path(tmp) / "bad.csv"
            bad_path.write_text("노선그룹,출발지,도착지,항공사,출국편,귀국편,항공일수,조회종료일,조회인원\nICN-TAO,ICN,TAO,KE,KE843,KE844,2,2027-10-31,99\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "2행 오류"):
                c.import_routes_csv(bad_path)

    def test_inline_row_edit_and_comboboxes(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QMessageBox
        qt_app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            routes_path = Path(tmp) / "sabre-routes.json"
            c.save_routes(routes_path, [
                c.normalize_route({"origin": "ICN", "destination": "TAO", "airline": "KE",
                                   "depFlight": "KE843", "retFlight": "KE844", "days": "2", "endDate": "2027-10-31"})
            ])
            orig_path = app_mod.ROUTES_PATH
            app_mod.ROUTES_PATH = routes_path
            gui = app_mod.App()
            try:
                self.assertIsNone(gui.manage_win)
                gui.open_manage_window()
                mgr = gui.manage_win
                self.assertIsNotNone(mgr)
                gui.open_manage_window()
                self.assertIs(gui.manage_win, mgr)  # 중복 창 생성 방지
                mgr.start_row_edit(0, focus_col=8)
                self.assertIsNotNone(mgr.edit_state)
                self.assertIsInstance(mgr.edit_state["widgets"]["fareOnly"], QComboBox)
                self.assertIsInstance(mgr.edit_state["widgets"]["enabled"], QComboBox)
                self.assertIsInstance(mgr.edit_state["widgets"]["pax"], QLineEdit)
                rg_edit = mgr.edit_state["widgets"]["routeGroup"]
                rg_edit.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
                self.assertEqual(rg_edit.cursorPosition(), len(rg_edit.text()))
                rg_edit.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier))
                self.assertEqual(rg_edit.cursorPosition(), 0)
                mgr.edit_state["widgets"]["pax"].setText("4")
                mgr.edit_state["widgets"]["bookingClass"].setText("S")
                mgr.edit_state["widgets"]["fareOnly"].setCurrentText("TOTAL KRW")
                mgr.edit_state["widgets"]["enabled"].setCurrentText("중지")
                self.assertTrue(mgr.commit_row_edit())
                self.assertIsNone(mgr.edit_state)
                saved = c.load_routes(routes_path)
                self.assertEqual((saved[0]["pax"], saved[0]["bookingClass"], saved[0]["fareOnly"], saved[0]["enabled"]),
                                 (4, "S", False, False))
                # 노선 추가 후 Esc 취소 시 임시 행이 제거되고 목록은 변하지 않아야 한다
                mgr.add_route_row()
                self.assertEqual(mgr.table.rowCount(), 2)
                mgr.cancel_row_edit()
                self.assertEqual(mgr.table.rowCount(), 1)
                self.assertEqual(len(gui.routes), 1)
                # 노선 복사 시 선택 행 바로 아래에 복제되고 선택·포커스가 복사 행으로 이동해야 한다
                mgr.table.setCurrentCell(0, 0)
                mgr.copy_route_row()
                self.assertEqual(len(gui.routes), 2)
                self.assertEqual(mgr.table.currentRow(), 1)
                self.assertEqual(gui.routes[1], gui.routes[0])
                self.assertIsNot(gui.routes[1]["days"], gui.routes[0]["days"])
                # 연속된 동일 노선그룹은 0열 병합, 개별 행 편집 시 임시 해제 후 취소 시 복원
                self.assertEqual(mgr.table.rowSpan(0, 0), 2)
                mgr.start_row_edit(1, focus_col=0)
                self.assertEqual(mgr.table.rowSpan(0, 0), 1)
                mgr.cancel_row_edit()
                self.assertEqual(mgr.table.rowSpan(0, 0), 2)
                # 우클릭 메뉴: 빈칸 -> 노선 추가, 기존 행 -> 해당 행 선택 + 노선 복사/노선 삭제
                m_blank = mgr.build_context_menu(-1)
                self.assertEqual([a.text() for a in m_blank.actions()], ["노선 추가"])
                m_row = mgr.build_context_menu(0)
                self.assertEqual(mgr.table.currentRow(), 0)
                self.assertEqual([a.text() for a in m_row.actions()], ["노선 복사", "노선 삭제"])
                # 빈 신규 노선 행에서 입력 없이 나가면 경고 후 삭제
                warned = []
                orig_warn = QMessageBox.warning
                QMessageBox.warning = staticmethod(lambda _p, title, msg: warned.append((title, msg)))
                try:
                    mgr.add_route_row()
                    self.assertEqual(mgr.table.rowCount(), 3)
                    self.assertEqual(
                        (mgr.edit_state["widgets"]["pax"].text(), mgr.edit_state["widgets"]["bookingClass"].text(),
                         mgr.edit_state["widgets"]["fareOnly"].currentText(), mgr.edit_state["widgets"]["enabled"].currentText()),
                        ("4", "Y", "FARE KRW", "사용"),
                    )
                    self.assertTrue(mgr.commit_row_edit())
                    self.assertEqual(len(warned), 1)
                    self.assertEqual(mgr.table.rowCount(), 2)
                    self.assertEqual(len(gui.routes), 2)
                finally:
                    QMessageBox.warning = orig_warn
                # 부분 입력 노선 행은 저장되지만 자동조회(group_routes/job_entries/CLI)에는 노출되지 않음
                mgr.add_route_row()
                mgr.edit_state["widgets"]["origin"].setText("ICN")
                mgr.edit_state["widgets"]["airline"].setText("KE")
                self.assertTrue(mgr.commit_row_edit())
                self.assertEqual(len(gui.routes), 3)
                self.assertFalse(c.is_complete_route(gui.routes[2]))
                self.assertEqual(gui.job_entries, [])  # 0·1번은 중지, 2번은 미완성
                self.assertEqual(cli.select_jobs(gui.routes, select_all=True), [])
                # 나머지 필수 필드를 모두 채우면 즉시 자동조회에 노출됨
                mgr.start_row_edit(2, focus_col=2)
                mgr.edit_state["widgets"]["destination"].setText("DAD")
                mgr.edit_state["widgets"]["depFlight"].setText("KE457")
                mgr.edit_state["widgets"]["retFlight"].setText("KE458")
                mgr.edit_state["widgets"]["days"].setText("2,3")
                mgr.edit_state["widgets"]["endDate"].setText("2027-10-31")
                self.assertTrue(mgr.commit_row_edit())
                self.assertTrue(c.is_complete_route(gui.routes[2]))
                self.assertEqual(len(gui.job_entries), 2)
                # 개별 노선 체크박스는 항상 선택 가능하고, 1개만 체크해도 전체해제로 전환됨
                g0, cb0, _, _ = gui.job_entries[0]
                _, cb1, _, _ = gui.job_entries[1]
                self.assertTrue(cb0.isEnabled())
                self.assertEqual(gui.group_cards[g0][1].text(), "전체선택")
                cb0.setChecked(True)
                gui.update_detail_states()
                self.assertFalse(cb1.isChecked())
                self.assertEqual(gui.group_cards[g0][1].text(), "전체해제")
                self.assertEqual(len(gui.selected_jobs()), 1)
                gui.toggle_group_jobs(g0)
                self.assertFalse(cb0.isChecked())
                self.assertFalse(cb1.isChecked())
                self.assertEqual(gui.group_cards[g0][1].text(), "전체선택")
                self.assertEqual(gui.selected_jobs(), [])
                # 메인 검색바: 필터링 및 검색어 변경 후에도 기존 선택 유지
                gui.main_search_edit.setText("KE457")
                self.assertFalse(gui.group_cards[g0][0].isHidden())
                cb0.setChecked(True)
                gui.main_search_edit.setText("NO_MATCH_XYZ")
                self.assertTrue(gui.group_cards[g0][0].isHidden())
                self.assertEqual(len(gui.selected_jobs()), 1)
                gui.main_search_edit.setText("")
                self.assertFalse(gui.group_cards[g0][0].isHidden())
                cb0.setChecked(False)
                # 노선 검색: 노선그룹~귀국편 유연 검색 및 필터 상태에서도 원본 인덱스 유지
                mgr.search_edit.setText("KE 458")
                self.assertEqual([mgr._row_route_index(r) for r in range(mgr.table.rowCount())], [2])
                mgr.search_edit.setText("icndad")
                self.assertEqual([mgr._row_route_index(r) for r in range(mgr.table.rowCount())], [2])
                mgr.search_edit.setText("tao")
                self.assertEqual([mgr._row_route_index(r) for r in range(mgr.table.rowCount())], [0, 1])
                mgr.search_edit.setText("")
                self.assertEqual([mgr._row_route_index(r) for r in range(mgr.table.rowCount())], [0, 1, 2])
                # F2 키로 선택 행 인라인 편집 진입
                mgr.table.setCurrentCell(2, 0)
                mgr.on_f2()
                self.assertIsNotNone(mgr.edit_state)
                self.assertEqual(mgr.edit_state["row"], 2)
                mgr.cancel_row_edit()
                # 상단 메뉴바(파일·설정·도움말), 파일 > 끝내기(Ctrl+Q), 설정 3종 확인
                top_labels = [a.text() for a in gui.menuBar().actions()]
                self.assertEqual(top_labels, ["파일", "설정", "도움말"])
                self.assertEqual(gui.quit_action.text(), "끝내기")
                self.assertEqual(gui.quit_action.shortcut().toString(), "Ctrl+Q")
                settings_labels = [a.text() for a in gui.settings_menu.actions()]
                self.assertEqual(settings_labels, ["로그인 정보", "엑셀 저장 경로", "조회 노선 관리"])
                # 저장된 로그인 정보가 있으면 LoginDialog에 마스킹 표시되고 빈칸은 기존 값 유지
                dlg = app_mod.LoginDialog(gui, saved_cfg={"agentId": "4028", "password": "secret", "pcc": "R4D8", "remember": True}, submit_label="저장")
                self.assertIn("4**8", dlg.saved_summary_text)
                self.assertIn("******", dlg.saved_summary_text)
                self.assertIn("R**8", dlg.saved_summary_text)
                self.assertNotIn("secret", dlg.saved_summary_text)
                dlg.pw_edit.setText("newpw")
                dlg.submit()
                self.assertEqual(dlg.result_data, {"agentId": "4028", "password": "newpw", "pcc": "R4D8", "remember": True})
                # 엑셀 저장 경로 설정 팝업
                out_dlg = app_mod.OutputPathDialog(gui, Path(tmp))
                out_dlg.path_edit.setText(str(Path(tmp) / "fares"))
                out_dlg.submit()
                self.assertEqual(out_dlg.result_path, str(Path(tmp) / "fares"))
                # 시작일 기본값(오늘+3일) 및 한달/분기/반기/일년 종료일 프리셋 확인
                from datetime import timedelta as td
                self.assertEqual(gui.start_edit.text(), (date.today() + td(3)).isoformat())
                gui.start_edit.setText("2026-01-31")
                gui.set_end_preset(1)
                self.assertEqual(gui.end_edit.text(), "2026-02-28")
                gui.set_end_preset(3)
                self.assertEqual(gui.end_edit.text(), "2026-04-30")
                gui.set_end_preset(6)
                self.assertEqual(gui.end_edit.text(), "2026-07-31")
                gui.set_end_preset(12)
                self.assertEqual(gui.end_edit.text(), "2027-01-31")
                # 전체 진행바: 2개 노선(2일 + 3일 = 총 5일) 누적 진행률 검증
                prog_events = []
                orig_run, orig_log = t.run_job, gui.log
                def fake_run_job(route, days, start, end, today, log, stop, **_kw):
                    n = (end - start).days + 1
                    for i in range(1, n + 1):
                        log(f"[{i}/{n}]", (i, n))
                    return Path(tmp) / f"{route['airline']}_{days}.xlsx"
                gui.log = lambda msg, progress=None: prog_events.append(progress) if progress else None
                t.run_job = fake_run_job
                try:
                    r1 = {**gui.routes[2], "endDate": "2026-12-02"}
                    r2 = {**gui.routes[2], "airline": "OZ", "depFlight": "OZ101", "endDate": "2026-12-03"}
                    # 그룹 통합 엑셀 생성 방지를 위해 다른 routeGroup 사용
                    r2["routeGroup"] = "ICN-DAD-OZ"
                    gui.worker([(r1, 2), (r2, 3)], date(2026, 12, 1), None)
                    self.assertEqual(prog_events, [(0, 5), (1, 5), (2, 5), (2, 5), (3, 5), (4, 5), (5, 5), (5, 5)])
                finally:
                    t.run_job, gui.log = orig_run, orig_log
                mgr.close()
                qt_app.processEvents()
            finally:
                app_mod.ROUTES_PATH = orig_path
                gui.close()
                qt_app.processEvents()

    def test_cli_select_jobs_and_summary(self):
        routes = [
            c.normalize_route({"routeGroup": "ICN-TAO", "region": "칭다오", "origin": "ICN", "destination": "TAO",
                               "airline": "KE", "depFlight": "KE843", "retFlight": "KE844", "days": "2,3", "endDate": "2027-10-31"}),
            c.normalize_route({"routeGroup": "ICN-CKG", "region": "중경", "origin": "ICN", "destination": "CKG",
                               "airline": "CA", "depFlight": "CA440", "retFlight": "CA439", "days": "3", "endDate": "2027-10-31"}),
        ]
        self.assertEqual([(r["region"], d) for r, d in cli.select_jobs(routes, groups=["icn-tao"])], [("칭다오", 2), ("칭다오", 3)])
        self.assertEqual([(r["region"], d) for r, d in cli.select_jobs(routes, regions=["충칭"])], [("중경", 3)])
        self.assertEqual([(r["region"], d) for r, d in cli.select_jobs(routes, groups=["ICN-TAO"], days_filter=[2])], [("칭다오", 2)])
        self.assertEqual(cli.select_jobs(routes), [])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.xlsx"
            c.save_workbook(p, "B", {date(2026, 12, 1): 150000, date(2026, 12, 2): c.SOLD, date(2026, 12, 3): c.ERR})
            s = cli.summarize_workbook(p)
            self.assertEqual((s["totalDays"], s["fares"], s["soldOut"], s["errors"]), (3, 1, 1, 1))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.xlsx"
            res = {date(2026, 12, 1): 340000, date(2026, 12, 2): c.SOLD}
            c.save_workbook(p, "B", res)
            c.verify_workbook(p, "B", date(2026, 12, 1), date(2026, 12, 2))
            with self.assertRaises(ValueError):
                c.verify_workbook(p, "B", date(2026, 12, 1), date(2026, 12, 3))

    def test_group_summary_workbook_matches_reference_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r_lj = c.normalize_route({'routeGroup': 'ICN-BKK-LCC', 'origin': 'ICN', 'destination': 'BKK',
                                      'airline': 'LJ', 'depFlight': 'LJ001', 'retFlight': 'LJ002', 'days': '3', 'endDate': '2027-02-26'})
            r_tw = c.normalize_route({'routeGroup': 'ICN-BKK-LCC', 'origin': 'ICN', 'destination': 'BKK',
                                      'airline': 'TW', 'depFlight': 'TW101', 'retFlight': 'TW102', 'days': '4', 'endDate': '2027-03-25'})
            p_lj = root / 'lj.xlsx'
            p_tw = root / 'tw.xlsx'
            c.save_workbook(p_lj, 'B', {date(2026, 11, 20): c.SOLD, date(2026, 11, 21): 260000})
            c.save_workbook(p_tw, 'B', {date(2026, 11, 20): 308000, date(2026, 11, 21): 288000, date(2026, 11, 22): c.SOLD})
            out = c.group_summary_path('ICN-BKK-LCC', 'BKK', date(2026, 11, 20), root=root)
            c.save_group_summary_workbook(out, 'ICN-BKK-LCC', [(r_lj, 3, p_lj), (r_tw, 4, p_tw)])
            wb = c.load_workbook(out, data_only=False)
            try:
                ws = wb.active
                self.assertEqual(ws.title, 'ICN-BKK-LCC')
                self.assertEqual([ws.cell(2, col).value for col in range(1, 8)],
                                 [None, 'LJ001', 'TW101', None, '날짜', '최저가', '최저가 항공'])
                self.assertEqual(ws['B3'].value, c.SOLD)
                self.assertEqual(ws['B3'].fill.start_color.rgb, 'FFFCE4D6')
                self.assertEqual(ws['C3'].value, 308000)
                self.assertEqual(ws['E3'].value, '=A3')
                self.assertEqual(ws['F3'].value, '=IF(COUNT(B3:C3)=0,"예약마감",MIN(B3:C3))')
                self.assertEqual(ws['G3'].value, '=IF(ISNUMBER(F3),IFERROR(INDEX($B$2:$C$2,1,MATCH(F3,B3:C3,0)),""),"")')
                self.assertIsNone(ws['B5'].value)
                self.assertEqual(ws['C5'].value, c.SOLD)
            finally:
                wb.close()
            out2 = root / 'dup.xlsx'
            c.save_group_summary_workbook(out2, 'ICN-TAO-KE', [(r_lj, 2, p_lj), (r_lj, 3, p_lj)])
            wb2 = c.load_workbook(out2, data_only=False)
            try:
                self.assertEqual([wb2.active['B2'].value, wb2.active['C2'].value], ['LJ001(+2)', 'LJ001(+3)'])
            finally:
                wb2.close()

    def test_login_config_remember_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "sabre-config.json"
            self.assertFalse(app_mod.has_saved_login(app_mod.read_config(cfg_path)))
            # remember 키가 없는 기존 설정은 첫 실행 시 팝업을 띄우도록 False 판정
            cfg_path.write_text('{"agentId":"u1","password":"p1","pcc":"R4D8"}', encoding="utf-8")
            self.assertFalse(app_mod.has_saved_login(app_mod.read_config(cfg_path)))
            # 로그인 정보 기억하기 저장 후 2회차부터 True
            app_mod.save_login_config({"agentId": " u1 ", "password": "p1", "pcc": "r4d8"}, cfg_path)
            saved = app_mod.read_config(cfg_path)
            self.assertTrue(app_mod.has_saved_login(saved))
            self.assertEqual((saved["agentId"], saved["pcc"], saved["remember"]), ("u1", "R4D8", True))
            # 인증 실패 등으로 기억 해제 시 비밀번호와 remember 초기화
            app_mod.clear_remembered_login(cfg_path)
            cleared = app_mod.read_config(cfg_path)
            self.assertFalse(app_mod.has_saved_login(cleared))
            self.assertEqual(cleared["password"], "")
            self.assertEqual(cleared["pcc"], "R4D8")
            # 마스킹 및 엑셀 저장 경로와 로그인 설정 상호 보존 확인
            self.assertEqual(app_mod.mask_secret("4028"), "4**8")
            self.assertEqual(app_mod.mask_secret("R4D8"), "R**8")
            self.assertEqual(app_mod.mask_secret("agent01"), "ag****1")
            self.assertEqual(app_mod.mask_secret("secret", full=True), "******")
            custom_dir = Path(tmp) / "custom_excel"
            app_mod.save_output_root(custom_dir, cfg_path)
            self.assertEqual(app_mod.get_output_root(path=cfg_path), custom_dir)
            app_mod.save_login_config({"agentId": "4028", "password": "secret", "pcc": "R4D8"}, cfg_path)
            self.assertEqual(app_mod.get_output_root(path=cfg_path), custom_dir)
            route = {"region": "칭다오", "origin": "ICN", "destination": "TAO", "airline": "KE"}
            self.assertEqual(c.output_path(route, 2, date(2026, 11, 20), root=custom_dir).parent, custom_dir / "칭다오")

    def test_login_dialog_flow_first_and_second_run(self):
        import time
        from PySide6.QtWidgets import QApplication, QDialog
        qt_app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "sabre-config.json"
            orig_cfg, orig_dlg, orig_launch = app_mod.CONFIG_PATH, app_mod.LoginDialog, t.launch_and_login
            app_mod.CONFIG_PATH = cfg_path
            launched, dialog_calls, next_result = [], 0, [None]

            class FakeDialog:
                def __init__(self, parent):
                    nonlocal dialog_calls
                    dialog_calls += 1
                    self.result_data = next_result[0]
                def exec(self):
                    return QDialog.DialogCode.Accepted if self.result_data else QDialog.DialogCode.Rejected

            def fake_launch(cfg, log, stop):
                launched.append(dict(cfg))
                return True

            gui = app_mod.App()
            try:
                app_mod.LoginDialog = FakeDialog
                t.launch_and_login = fake_launch

                # 1) 팝업 취소 시 브라우저 연결 안 함
                next_result[0] = None
                gui.login()
                self.assertEqual(dialog_calls, 1)
                self.assertEqual(launched, [])

                # 2) 기억하기 체크 해제 로그인 -> 파일 저장 없이 세션 메모리로 연결
                next_result[0] = {"agentId": "A1", "password": "PW1", "pcc": "R4D8", "remember": False}
                gui.login()
                for _ in range(30):
                    if launched:
                        break
                    time.sleep(0.02)
                self.assertEqual(dialog_calls, 2)
                self.assertEqual(len(launched), 1)
                self.assertEqual(launched[0]["agentId"], "A1")
                self.assertFalse(cfg_path.exists())
                self.assertEqual(gui.load_cfg()["agentId"], "A1")

                # 3) 기억하기 체크 로그인 -> sabre-config.json 저장 후 연결
                next_result[0] = {"agentId": "A2", "password": "PW2", "pcc": "R4D8", "remember": True}
                gui.login()
                for _ in range(30):
                    if len(launched) >= 2:
                        break
                    time.sleep(0.02)
                self.assertEqual(dialog_calls, 3)
                self.assertEqual(len(launched), 2)
                self.assertTrue(app_mod.has_saved_login(app_mod.read_config(cfg_path)))

                # 4) 2회차 클릭 -> 팝업 없이 즉시 브라우저 연결
                gui.login()
                for _ in range(30):
                    if len(launched) >= 3:
                        break
                    time.sleep(0.02)
                self.assertEqual(dialog_calls, 3)  # 팝업 추가 호출 없음
                self.assertEqual(len(launched), 3)
                self.assertEqual(launched[2]["agentId"], "A2")
            finally:
                app_mod.CONFIG_PATH, app_mod.LoginDialog, t.launch_and_login = orig_cfg, orig_dlg, orig_launch
                gui.close()
                qt_app.processEvents()


if __name__ == "__main__":
    unittest.main()

