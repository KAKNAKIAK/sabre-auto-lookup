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
        # 나트랑(CXR)은 Sabre 운임계산식에 도시코드 NHA로 출력된다
        cxr_api = (
            "FARE  KRW    286200  \n"
            "TAX   KRW     24000BP KRW     26700JC KRW    239900XT\n"
            "TOTAL KRW    576800\n"
            " SEL ZE NHA106.60ZE SEL106.60NUC213.20END ROE1342.36847\n"
            " 1 ZE 561R 01DEC 2 ICNCXR SS4  2050  0020  02DEC 3 /DCZE /E\n"
            " 2 ZE 562R 04DEC 5 CXRICN SS4  0155  0850  /DCZE /E\n"
        )
        self.assertEqual(c.parse_wpncb(cxr_api, "ZE", "ICN", "CXR", 561, 562, "01DEC", "04DEC", pax=4, fare_only=True), 286200)
        self.assertEqual(c.parse_wpncb(cxr_api, "ZE", "ICN", "CXR", 561, 562, "01DEC", "04DEC", pax=4, fare_only=False), 576800)
        # CITY 매핑에 없는 신규 공항(예: ZZZ -> QQQ)도 출·귀국 세그 2줄이 정확히 일치하면 정상 파싱
        unmapped_api = (
            "FARE  KRW    310000\nTOTAL KRW    450000\n"
            " SEL KE QQQ100.00KE SEL100.00NUC200.00END\n"
            " 1 KE 901Y 01DEC 2 ICNZZZ SS2  1000  1300  /DCKE /E\n"
            " 2 KE 902Y 04DEC 5 ZZZICN SS2  1500  1800  /DCKE /E\n"
        )
        self.assertEqual(c.parse_wpncb(unmapped_api, "KE", "ICN", "ZZZ", 901, 902, "01DEC", "04DEC", pax=2, fare_only=True), 310000)

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

    def test_force_navigate_page_accepts_beforeunload_on_dead_session(self):
        import json
        sent = []
        incoming = iter([
            json.dumps({"id": 1, "result": {}}),  # Page.enable
            json.dumps({"method": "Page.javascriptDialogOpening", "params": {"type": "beforeunload"}}),
            json.dumps({"id": 3, "result": {}}),  # handleJavaScriptDialog
            json.dumps({"id": 2, "result": {"frameId": "F1"}}),  # Page.navigate
            json.dumps({"id": 4, "result": {}}),  # follow-up handleJavaScriptDialog
        ])
        class FakeWS:
            def send(self, payload):
                sent.append(json.loads(payload))
            def recv(self):
                return next(incoming)
        page = t.Page.__new__(t.Page)
        page.ws = FakeWS()
        page.seq = 0
        orig_sleep = t.time.sleep
        t.time.sleep = lambda _s: None
        try:
            t._force_navigate_page(page, t.LOGIN_URL)
            methods = [m["method"] for m in sent]
            self.assertIn("Page.navigate", methods)
            self.assertIn("Page.handleJavaScriptDialog", methods)
        finally:
            t.time.sleep = orig_sleep

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

    def _run_with_gui(self, routes, fn):
        from PySide6.QtWidgets import QApplication
        qt_app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            routes_path = Path(tmp) / "sabre-routes.json"
            c.save_routes(routes_path, routes)
            orig_path = app_mod.ROUTES_PATH
            app_mod.ROUTES_PATH = routes_path
            gui = app_mod.App()
            try:
                fn(gui, Path(tmp), routes_path, qt_app)
            finally:
                app_mod.ROUTES_PATH = orig_path
                gui.close()
                qt_app.processEvents()

    def test_manage_window_inline_edit_merge_copy_paste(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QComboBox, QLineEdit, QMessageBox

        seed = [c.normalize_route({"origin": "ICN", "destination": "TAO", "airline": "KE",
                                   "depFlight": "KE843", "retFlight": "KE844", "days": "2", "endDate": "2027-10-31"})]

        def body(gui, tmp, routes_path, qt_app):
            self.assertIsNone(gui.manage_win)
            gui.open_manage_window()
            mgr = gui.manage_win
            self.assertIsNotNone(mgr)
            # 조회시작일이 공란이면 표에 메인 화면의 시작일 값을 표시하되 저장값은 공란 유지
            start_col = app_mod.MANAGE_COLS.index("startDate")
            self.assertEqual(mgr.table.item(0, start_col).text(), gui.start_edit.text())
            gui.start_edit.setText("2026-12-03")
            gui._on_main_start_finished()
            self.assertEqual(mgr.table.item(0, start_col).text(), "2026-12-03")
            self.assertEqual(mgr.close_sc.key().toString(), "Ctrl+Q")
            self.assertTrue(bool(mgr.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint))
            app_mod.toggle_window_maximize(mgr)
            self.assertTrue(mgr.isMaximized())
            app_mod.toggle_window_maximize(mgr)
            self.assertFalse(mgr.isMaximized())
            gui.open_manage_window()
            self.assertIs(gui.manage_win, mgr)
            mgr.start_row_edit(0, focus_col=app_mod.MANAGE_COLS.index("pax"))
            self.assertIsNotNone(mgr.edit_state)
            self.assertIsInstance(mgr.edit_state["widgets"]["fareOnly"], QComboBox)
            self.assertIsInstance(mgr.edit_state["widgets"]["enabled"], QComboBox)
            self.assertIsInstance(mgr.edit_state["widgets"]["pax"], QLineEdit)
            self.assertIn("startDate", mgr.edit_state["widgets"])
            rg_edit = mgr.edit_state["widgets"]["routeGroup"]
            rg_edit.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
            self.assertEqual(rg_edit.cursorPosition(), len(rg_edit.text()))
            rg_edit.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier))
            self.assertEqual(rg_edit.cursorPosition(), 0)
            mgr.edit_state["widgets"]["pax"].setText("4")
            mgr.edit_state["widgets"]["bookingClass"].setText("S")
            mgr.edit_state["widgets"]["startDate"].setText("2026-12-15")
            mgr.edit_state["widgets"]["fareOnly"].setCurrentText("TOTAL KRW")
            mgr.edit_state["widgets"]["enabled"].setCurrentText("중지")
            self.assertTrue(mgr.commit_row_edit())
            self.assertIsNone(mgr.edit_state)
            saved = c.load_routes(routes_path)
            self.assertEqual((saved[0]["startDate"], saved[0]["pax"], saved[0]["bookingClass"], saved[0]["fareOnly"], saved[0]["enabled"]),
                             ("2026-12-15", 4, "S", False, False))
            self.assertEqual(c.effective_start(saved[0], date(2026, 11, 23)), date(2026, 12, 15))
            self.assertEqual(c.effective_start(saved[0], date(2027, 1, 5)), date(2027, 1, 5))
            mgr.add_route_row()
            self.assertEqual(mgr.table.rowCount(), 2)
            mgr.cancel_row_edit()
            self.assertEqual(mgr.table.rowCount(), 1)
            mgr.table.setCurrentCell(0, 0)
            mgr.copy_route_row()
            self.assertEqual((len(gui.routes), mgr.table.currentRow()), (2, 1))
            self.assertIsNot(gui.routes[1]["days"], gui.routes[0]["days"])
            self.assertEqual(mgr.table.rowSpan(0, 0), 2)
            mgr.start_row_edit(1, focus_col=0)
            self.assertEqual(mgr.table.rowSpan(0, 0), 1)
            mgr.cancel_row_edit()
            self.assertEqual(mgr.table.rowSpan(0, 0), 2)
            self.assertEqual([a.text() for a in mgr.build_context_menu(-1).actions()], ["노선 추가", "붙여넣기로 노선 추가"])
            self.assertEqual(mgr.blank_zone.height(), 52)
            self.assertEqual(mgr.table.verticalScrollMode(), mgr.table.ScrollMode.ScrollPerPixel)
            self.assertEqual([a.text() for a in mgr.build_context_menu(0).actions()], ["노선 복사", "노선 삭제", "최종 조회일 업데이트"])
            self.assertEqual(mgr.table.currentRow(), 0)
            warned = []
            orig_warn = QMessageBox.warning
            QMessageBox.warning = staticmethod(lambda _p, title, msg: warned.append((title, msg)))
            try:
                mgr.add_route_row()
                self.assertEqual(
                    (mgr.edit_state["widgets"]["pax"].text(), mgr.edit_state["widgets"]["bookingClass"].text(),
                     mgr.edit_state["widgets"]["fareOnly"].currentText(), mgr.edit_state["widgets"]["enabled"].currentText()),
                    ("4", "Y", "FARE KRW", "사용"),
                )
                self.assertTrue(mgr.commit_row_edit())
                self.assertEqual((len(warned), len(gui.routes)), (1, 2))
            finally:
                QMessageBox.warning = orig_warn
            mgr.add_route_row()
            mgr.edit_state["widgets"]["origin"].setText("ICN")
            mgr.edit_state["widgets"]["airline"].setText("KE")
            self.assertTrue(mgr.commit_row_edit())
            self.assertFalse(c.is_complete_route(gui.routes[2]))
            self.assertEqual(gui.job_entries, [])
            self.assertEqual(cli.select_jobs(gui.routes, select_all=True), [])
            mgr.start_row_edit(2, focus_col=2)
            mgr.edit_state["widgets"]["destination"].setText("DAD")
            mgr.edit_state["widgets"]["depFlight"].setText("KE457")
            mgr.edit_state["widgets"]["retFlight"].setText("KE458")
            mgr.edit_state["widgets"]["days"].setText("2,3")
            mgr.edit_state["widgets"]["endDate"].setText("2027-10-31")
            self.assertTrue(mgr.commit_row_edit())
            self.assertTrue(c.is_complete_route(gui.routes[2]))
            mgr.search_edit.setText("KE 458")
            self.assertEqual([mgr._row_route_index(r) for r in range(mgr.table.rowCount())], [2])
            mgr.search_edit.setText("icndad")
            self.assertEqual([mgr._row_route_index(r) for r in range(mgr.table.rowCount())], [2])
            mgr.search_edit.setText("tao")
            self.assertEqual([mgr._row_route_index(r) for r in range(mgr.table.rowCount())], [0, 1])
            mgr.search_edit.setText("")
            self.assertEqual([mgr._row_route_index(r) for r in range(mgr.table.rowCount())], [0, 1, 2])
            mgr.table.setCurrentCell(2, 0)
            mgr.on_f2()
            self.assertEqual(mgr.edit_state["row"], 2)
            mgr.cancel_row_edit()
            end_col = app_mod.MANAGE_COLS.index("endDate")
            mgr.table.clearSelection()
            mgr.table.setCurrentCell(2, end_col)
            # 셀 클릭 시 해당 행 전체가 붉은 계통(#fee2e2)으로 강조되고 다른 행은 기본색 유지
            self.assertEqual(mgr.table.item(2, 1).background().color().name().lower(), "#fee2e2")
            self.assertNotEqual(mgr.table.item(0, 1).background().color().name().lower(), "#fee2e2")
            # 병합된 노선그룹(0열, 0~1행 병합) 클릭 시 병합된 모든 행 전체가 붉은 계통으로 강조됨
            mgr.table.clearSelection()
            mgr.table.setCurrentCell(0, 0)
            self.assertEqual(mgr.table.item(0, 1).background().color().name().lower(), "#fee2e2")
            self.assertEqual(mgr.table.item(1, 1).background().color().name().lower(), "#fee2e2")
            mgr.table.clearSelection()
            mgr.table.setCurrentCell(2, end_col)
            self.assertEqual(mgr.copy_selected_cells(), "2027-10-31")
            mgr.table.item(0, end_col).setSelected(True)
            mgr.table.item(1, end_col).setSelected(True)
            self.assertTrue(mgr.paste_to_selected_cells("2027/12/25"))
            self.assertEqual((gui.routes[0]["endDate"], gui.routes[1]["endDate"]), ("2027-12-25", "2027-12-25"))
            mgr.table.clearSelection()
            mgr.table.setCurrentCell(0, app_mod.MANAGE_COLS.index("pax"))
            self.assertTrue(mgr.paste_to_selected_cells("3\tM\n2\tQ\n"))
            self.assertEqual((gui.routes[0]["pax"], gui.routes[0]["bookingClass"]), (3, "M"))
            self.assertEqual((gui.routes[1]["pax"], gui.routes[1]["bookingClass"]), (2, "Q"))
            errs = []
            orig_crit = QMessageBox.critical
            QMessageBox.critical = staticmethod(lambda _p, title, msg: errs.append((title, msg)))
            try:
                mgr.table.clearSelection()
                mgr.table.setCurrentCell(0, app_mod.MANAGE_COLS.index("pax"))
                self.assertFalse(mgr.paste_to_selected_cells("99"))
                self.assertEqual((len(errs), gui.routes[0]["pax"]), (1, 3))
            finally:
                QMessageBox.critical = orig_crit
            mgr.table.clearSelection()
            mgr.table.setCurrentCell(2, 0)
            excel_tsv = (
                "노선그룹\t출발지\t도착지\t항공사\t출국편\t귀국편\t항공일수\t조회시작일\t조회종료일\t조회인원\t조회클래스\t운임기준\t사용\n"
                "ICN-DAD\tICN\tDAD\tKE\tKE457\tKE458\t2,3\t\t2027-10-31\t4\tY\tFARE KRW\t사용\n"
                "ICN-BKK-LCC\tICN\tBKK\tLJ\tLJ001\tLJ002\t3\t2026/12/1\t2027/2/26\t4\tY\tTOTAL KRW\t중지\n"
            )
            self.assertTrue(mgr.paste_to_selected_cells(excel_tsv))
            self.assertEqual(len(gui.routes), 4)
            self.assertEqual((gui.routes[3]["routeGroup"], gui.routes[3]["depFlight"], gui.routes[3]["startDate"],
                              gui.routes[3]["endDate"], gui.routes[3]["fareOnly"], gui.routes[3]["enabled"]),
                             ("ICN-BKK-LCC", "LJ001", "2026-12-01", "2027-02-26", False, False))
            # 노선 추가(신규 인라인 행) 상태에서 4개 행 붙여넣기 시 4개 신규 노선 즉시 추가
            four_rows = (
                "ICN-NEW\tICN\tBKK\tLJ\tLJ101\tLJ102\t3\t\t2027-03-01\t4\tY\tFARE KRW\t사용\n"
                "ICN-NEW\tICN\tBKK\tTW\tTW201\tTW202\t3\t\t2027-03-01\t4\tY\tFARE KRW\t사용\n"
                "ICN-NEW\tICN\tBKK\tYP\tYP301\tYP302\t3\t\t2027-03-01\t4\tY\tFARE KRW\t사용\n"
                "ICN-NEW\tICN\tBKK\tZE\tZE401\tZE402\t3\t\t2027-03-01\t4\tY\tFARE KRW\t사용\n"
            )
            mgr.add_route_row()
            mgr._handle_inline_multi_paste(four_rows, 0)
            self.assertIsNone(mgr.edit_state)
            self.assertEqual(len(gui.routes), 8)
            self.assertEqual([r["depFlight"] for r in gui.routes[4:]], ["LJ101", "TW201", "YP301", "ZE401"])
            # 빈 공간 붙여넣기(force_append=True)로도 4개 행이 기존 행 덮어쓰기 없이 신규 추가됨
            self.assertTrue(mgr.paste_to_selected_cells(four_rows, force_append=True))
            self.assertEqual(len(gui.routes), 12)
            mgr.close()
            qt_app.processEvents()
            gui.routes = [
                c.normalize_route({"routeGroup": "ICN-BKK-LCC", "origin": "ICN", "destination": "BKK", "airline": "LJ",
                                   "depFlight": "LJ001", "retFlight": "LJ002", "days": "3", "endDate": "2027-02-26"}),
                c.normalize_route({"routeGroup": "ICN-TAO-KE", "origin": "ICN", "destination": "TAO", "airline": "KE",
                                   "depFlight": "KE843", "retFlight": "KE844", "days": "2", "endDate": "2027-10-31"}),
                c.normalize_route({"routeGroup": "ICN-DAD-KE", "origin": "ICN", "destination": "DAD", "airline": "KE",
                                   "depFlight": "KE457", "retFlight": "KE458", "days": "3", "endDate": "2027-10-31"}),
            ]
            gui.open_manage_window()
            self.assertEqual([c.route_group(r) for r in gui.routes], ["ICN-TAO-KE", "ICN-DAD-KE", "ICN-BKK-LCC"])
            self.assertEqual(list(gui.group_cards.keys()), ["ICN-TAO-KE", "ICN-DAD-KE", "ICN-BKK-LCC"])
            # 강조된 행을 한 번 더 좌클릭하면 선택 해제되어 원래 배경색으로 복원
            from PySide6.QtCore import QEvent, QPointF
            from PySide6.QtGui import QMouseEvent
            mgr2 = gui.manage_win
            mgr2.show()
            qt_app.processEvents()
            mgr2.table.setCurrentCell(0, 1)
            mgr2._update_row_highlight()
            self.assertEqual(mgr2._selected_visual_rows(), {0})
            self.assertEqual(mgr2.table.item(0, 1).background().color().name().lower(), "#fee2e2")
            rect = mgr2.table.visualItemRect(mgr2.table.item(0, 1))
            pt = QPointF(rect.center())
            press = QMouseEvent(QEvent.Type.MouseButtonPress, pt, pt, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            rel = QMouseEvent(QEvent.Type.MouseButtonRelease, pt, pt, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            mgr2.eventFilter(mgr2.table.viewport(), press)
            mgr2.eventFilter(mgr2.table.viewport(), rel)
            self.assertEqual(mgr2._selected_visual_rows(), set())
            self.assertNotEqual(mgr2.table.item(0, 1).background().color().name().lower(), "#fee2e2")
            gui.manage_win.close()

        self._run_with_gui(seed, body)

    def test_main_window_cards_search_and_menus(self):
        seed = [c.normalize_route({"origin": "ICN", "destination": "DAD", "airline": "KE",
                                   "depFlight": "KE457", "retFlight": "KE458", "days": "2,3", "endDate": "2027-10-31"})]

        def body(gui, tmp, _rp, _qt):
            self.assertEqual(len(gui.job_entries), 2)
            g0, cb0, _, _ = gui.job_entries[0]
            _, cb1, _, _ = gui.job_entries[1]
            self.assertTrue(cb0.isEnabled())
            self.assertEqual(gui.group_cards[g0][1].text(), "전체선택")
            cb0.setChecked(True)
            gui.update_detail_states()
            self.assertFalse(cb1.isChecked())
            self.assertEqual((gui.group_cards[g0][1].text(), gui.all_toggle_btn.text()), ("전체해제", "전체 해제"))
            gui.toggle_all_jobs()
            self.assertEqual((gui.group_cards[g0][1].text(), gui.all_toggle_btn.text(), gui.selected_jobs()),
                             ("전체선택", "전체 선택", []))
            gui.main_search_edit.setText("KE457")
            self.assertFalse(gui.group_cards[g0][0].isHidden())
            cb0.setChecked(True)
            gui.main_search_edit.setText("NO_MATCH_XYZ")
            self.assertTrue(gui.group_cards[g0][0].isHidden())
            self.assertEqual(len(gui.selected_jobs()), 1)
            gui.main_search_edit.setText("")
            self.assertFalse(gui.group_cards[g0][0].isHidden())
            self.assertFalse(gui.isMaximized())
            app_mod.toggle_window_maximize(gui)
            self.assertTrue(gui.isMaximized())
            app_mod.toggle_window_maximize(gui)
            self.assertFalse(gui.isMaximized())
            self.assertEqual([a.text() for a in gui.menuBar().actions()], ["파일", "설정", "도움말"])
            self.assertEqual((gui.max_action.text(), gui.max_action.shortcut().toString()), ("최대화", "Alt+Enter"))
            self.assertEqual((gui.quit_action.text(), gui.quit_action.shortcut().toString()), ("끝내기", "Ctrl+Q"))
            self.assertEqual([a.text() for a in gui.settings_menu.actions()], ["로그인 정보", "엑셀 저장 경로", "조회 노선 관리", "노선 백업 관리"])
            self.assertEqual(
                [a.shortcut().toString() for a in gui.settings_menu.actions()],
                ["Ctrl+L", "Ctrl+E", "Ctrl+R", "Ctrl+B"],
            )
            dlg = app_mod.LoginDialog(gui, saved_cfg={"agentId": "4028", "password": "secret", "pcc": "R4D8", "remember": True}, submit_label="저장")
            self.assertIn("4**8", dlg.saved_summary_text)
            self.assertIn("******", dlg.saved_summary_text)
            self.assertIn("R**8", dlg.saved_summary_text)
            self.assertNotIn("secret", dlg.saved_summary_text)
            dlg.pw_edit.setText("newpw")
            dlg.submit()
            self.assertEqual(dlg.result_data, {"agentId": "4028", "password": "newpw", "pcc": "R4D8", "remember": True})
            out_dlg = app_mod.OutputPathDialog(gui, tmp)
            out_dlg.path_edit.setText(str(tmp / "fares"))
            out_dlg.submit()
            self.assertEqual(out_dlg.result_path, str(tmp / "fares"))

        self._run_with_gui(seed, body)

    def test_main_window_dates_progress_and_single_date(self):
        import time
        from datetime import timedelta as td
        from PySide6.QtWidgets import QMessageBox

        seed = [c.normalize_route({"origin": "ICN", "destination": "DAD", "airline": "KE",
                                   "depFlight": "KE457", "retFlight": "KE458", "days": "2,3", "endDate": "2027-10-31"})]

        def body(gui, tmp, _rp, _qt):
            self.assertEqual(gui.start_edit.text(), (date.today() + td(3)).isoformat())
            gui.start_edit.setText("20261205")
            gui.start_edit.editingFinished.emit()
            self.assertEqual(gui.start_edit.text(), "2026-12-05")
            gui.end_edit.setText("20270315")
            gui.end_edit.editingFinished.emit()
            self.assertEqual(gui.end_edit.text(), "2027-03-15")
            self.assertEqual(c.normalize_date_text("20261399"), "20261399")
            gui.start_edit.setText("2026-01-31")
            for m, exp in ((1, "2026-02-28"), (3, "2026-04-30"), (6, "2026-07-31"), (12, "2027-01-31")):
                gui.set_end_preset(m)
                self.assertEqual(gui.end_edit.text(), exp)
            prog_events = []
            orig_run, orig_log = t.run_job, gui.log
            def fake_run_job(route, days, start, end, today, log, stop, **_kw):
                n = (end - start).days + 1
                for i in range(1, n + 1):
                    log(f"[{i}/{n}]", (i, n))
                return tmp / f"{route['airline']}_{days}.xlsx"
            gui.log = lambda msg, progress=None: prog_events.append(progress) if progress else None
            t.run_job = fake_run_job
            try:
                r1 = {**gui.routes[0], "endDate": "2026-12-02"}
                r2 = {**gui.routes[0], "routeGroup": "ICN-DAD-OZ", "airline": "OZ", "depFlight": "OZ101", "endDate": "2026-12-03"}
                gui.worker([(r1, 2, date(2026, 12, 1), date(2026, 12, 2)),
                            (r2, 3, date(2026, 12, 1), date(2026, 12, 3))])
                self.assertEqual(prog_events, [(0, 5), (1, 5), (2, 5), (2, 5), (3, 5), (4, 5), (5, 5), (5, 5)])
            finally:
                t.run_job, gui.log = orig_run, orig_log
            r_no_end = c.normalize_route({"origin": "ICN", "destination": "TAO", "airline": "KE",
                                          "depFlight": "KE843", "retFlight": "KE844", "days": "2", "endDate": ""})
            self.assertTrue(c.is_complete_route(r_no_end))
            self.assertIsNone(c.effective_end(r_no_end, None))
            self.assertEqual(c.effective_end(r_no_end, date(2027, 5, 1)), date(2027, 5, 1))
            r_bounded = c.normalize_route({"origin": "ICN", "destination": "BKK", "airline": "LJ",
                                           "depFlight": "LJ001", "retFlight": "LJ002", "days": "3",
                                           "startDate": "2026-12-10", "endDate": "2027-02-26"})
            self.assertEqual(c.effective_end(r_bounded, date(2027, 11, 1)), date(2027, 2, 26))
            self.assertEqual(c.effective_end(r_bounded, date(2027, 1, 15)), date(2027, 1, 15))
            valid_p, issues_p = c.plan_jobs([(r_no_end, 2), (r_bounded, 3)], date(2027, 3, 1), None)
            self.assertEqual((valid_p, len(issues_p)), ([], 2))
            warns = []
            orig_w = QMessageBox.warning
            QMessageBox.warning = staticmethod(lambda _p, title, msg: warns.append((title, msg)))
            try:
                gui.job_entries[0][1].setChecked(True)
                gui.start_edit.setText("2028-01-01")
                gui.end_edit.setText("")
                gui.start_run()
                self.assertEqual(len(warns), 1)
                self.assertTrue(gui.run_btn.isEnabled())
                gui.job_entries[0][1].setChecked(False)
            finally:
                QMessageBox.warning = orig_w
            gui.start_edit.setText("2027-05-01")
            gui.end_edit.setText("")
            gui.single_date_chk.setChecked(True)
            self.assertEqual((gui.start_lbl.text(), gui.end_lbl.text(), gui.end_edit.text()), ("한국출발일", "한국도착일", "2027-05-04"))
            self.assertTrue(all(b.isHidden() for b in gui.preset_btns))
            self.assertFalse(gui.single_pax_edit.isHidden())
            self.assertEqual((gui.single_pax_edit.text(), gui.run_btn.text(), gui.run_btn.objectName()), ("1", "▶ 최저가 확인", "SuccessBtn"))
            self.assertEqual([cb.text() for _, cb, _, _ in gui.job_entries if not cb.isHidden()], ["KE457/458"])
            captured_single = []
            orig_sw = gui.single_date_worker
            gui.single_date_worker = lambda planned, s, e, pax=1: captured_single.append((planned, s, e, pax))
            try:
                gui.job_entries[0][1].setChecked(True)
                gui.single_pax_edit.setText("2")
                gui.start_run()
                for _ in range(30):
                    if captured_single:
                        break
                    time.sleep(0.02)
                self.assertEqual((len(captured_single), captured_single[0][3], captured_single[0][0][0][0]["pax"]), (1, 2, 2))
                # 실행 중에는 단일 버튼이 '■ 정지'(DangerBtn)로 전환되고 클릭 시 stop 설정, 완료 시 복원
                self.assertEqual((gui.run_btn.text(), gui.run_btn.objectName()), ("■ 정지", "DangerBtn"))
                gui.on_run_button_click()
                self.assertTrue(gui.stop.is_set())
                self.assertEqual(gui.run_btn.text(), "정지 중...")
                gui.reset_buttons()
                self.assertEqual((gui.run_btn.text(), gui.run_btn.objectName()), ("▶ 최저가 확인", "SuccessBtn"))
                gui.job_entries[0][1].setChecked(False)
            finally:
                gui.single_date_worker = orig_sw
            gui.single_date_chk.setChecked(False)
            self.assertEqual((gui.start_lbl.text(), gui.end_lbl.text(), gui.end_edit.text()), ("시작일", "종료일", ""))
            self.assertTrue(gui.single_pax_edit.isHidden())
            self.assertEqual([cb.text() for _, cb, _, _ in gui.job_entries if not cb.isHidden()], ["KE457/458 +2", "KE457/458 +3"])
            gui.start_edit.setText("2026-12-01")
            gui.end_edit.setText("2026-12-05")
            gui.single_date_chk.setChecked(True)
            self.assertEqual(gui.end_edit.text(), "2026-12-05")
            gui.single_date_chk.setChecked(False)
            self.assertEqual(gui.end_edit.text(), "2026-12-05")

        self._run_with_gui(seed, body)

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

    def test_single_date_quote_parse_and_lowest_format(self):
        raw_hi = (
            'FARE  KRW    450000  \n'
            'TAX   KRW    255200YR\n'
            'TOTAL KRW    705200\n'
            ' 1 CA 440M 01MAY 6 ICNCKG SS1  1405  1700  /DCCA /E\n'
            ' 2 CA 439M 05MAY 3 CKGICN SS1  0830  1305  /DCCA /E\n'
        )
        raw_lo = (
            'FARE  KRW    410000  \n'
            'TAX   KRW    255200YR\n'
            'TOTAL KRW    665200\n'
            ' 1 CA 440S 01MAY 6 ICNCKG SS1  1405  1700  /DCCA /E\n'
            ' 2 CA 439S 05MAY 3 CKGICN SS1  0830  1305  /DCCA /E\n'
        )
        d_hi = c.parse_quote_detail(raw_hi)
        d_lo = c.parse_quote_detail(raw_lo)
        self.assertEqual((d_lo['base'], d_lo['tax'], d_lo['total']), (410000, 255200, 665200))
        r1 = {'routeGroup': 'ICN-CKG', 'origin': 'ICN', 'destination': 'CKG', 'airline': 'CA', 'depFlight': 'CA440', 'retFlight': 'CA439'}
        r2 = {'routeGroup': 'ICN-CKG', 'origin': 'ICN', 'destination': 'CKG', 'airline': 'CA', 'depFlight': 'CA442', 'retFlight': 'CA441'}
        r3 = {'routeGroup': 'ICN-CKG', 'origin': 'ICN', 'destination': 'CKG', 'airline': 'CA', 'depFlight': 'CA444', 'retFlight': 'CA443'}
        text = c.build_single_date_popup_text([
            {'route': r1, 'days': 4, 'dep': date(2027, 5, 1), 'fare': 450000, 'detail': d_hi},
            {'route': r2, 'days': 4, 'dep': date(2027, 5, 1), 'fare': 410000, 'detail': d_lo},
            {'route': r3, 'days': 4, 'dep': date(2027, 5, 1), 'fare': c.ERR, 'detail': None, 'reason': '출국편 미운항/가용없음: 01MAY CA444'},
        ], date(2027, 5, 1))
        expected = (
            '--------------------------------------------------------------★ 최저가\n'
            ' 1 CA 440S 01MAY 6 ICNCKG SS1  1405  1700  /DCCA /E\n'
            ' 2 CA 439S 05MAY 3 CKGICN SS1  0830  1305  /DCCA /E\n\n'
            'KRW 410000\t\t\t\t\n'
            'KRW 255200\tXT\t\n'
            'KRW 665200\tADT\n'
            '--------------------------------------------------------------'
        )
        self.assertTrue(text.startswith(expected + '\n\n[그 외 조회 결과]\n'))
        rest = text.split('[그 외 조회 결과]\n', 1)[1]
        self.assertNotIn('CA442/441', rest)
        self.assertIn('1. CA440/439 | 기본 KRW 450,000', rest)
        self.assertIn('1 CA 440M 01MAY 6 ICNCKG SS1  1405  1700  /DCCA /E', text)
        self.assertIn('2 CA 439M 05MAY 3 CKGICN SS1  0830  1305  /DCCA /E', text)
        self.assertIn('2. CA444/443 | 조회불가 (출국편 미운항/가용없음: 01MAY CA444)', rest)
        # 세그 줄이 빠진 WP 응답은 *I 보조 텍스트에서 세그를 추출
        d_star = c.parse_quote_detail('FARE KRW 410000\nTOTAL KRW 665200', seg_text=raw_lo)
        self.assertEqual(len(d_star['segments']), 2)
        # 4자리 편명(예: 7C2515Y처럼 항공사코드와 편번 사이 공백 없음) 세그 추출 및 익일 판별
        raw_7c = (
            'FARE  KRW    515000\nTOTAL KRW    825000\n'
            ' 1 7C2515Y 01DEC 2 ICNCNX SS2  1800  2210  /DC7C /E\n'
            ' 2 7C2516Y 04DEC 5 CNXICN SS2  2310  0620   05DEC 6 /DC7C /E\n'
        )
        d_7c = c.parse_quote_detail(raw_7c)
        self.assertEqual(len(d_7c['segments']), 2)
        self.assertEqual(c.seg_arrival_offset(d_7c['segments'][1]), 1)
        self.assertEqual(c.parse_wpncb(raw_7c, '7C', 'ICN', 'CNX', 2515, 2516, '01DEC', '04DEC', pax=2), 515000)
        # 야간 귀국편(+1 익일 도착) 판별 및 한국도착일 기준 arr-1 자동 보정 검증
        self.assertEqual(c.seg_arrival_offset(' 2 CA 439S 05MAY 3 CKGICN SS1  0830  1305  /DCCA /E'), 0)
        self.assertEqual(c.seg_arrival_offset(' 2 YP 602Y 10DEC 4 BKKICN SS1  2255  0615   11DEC 5 /DCYP /E'), 1)
        calls = []
        class FakeTerm:
            _last_wpncb = ''
        orig_qd = t.query_date
        def fake_qd(term, route, days, dep):
            calls.append((dep, days))
            if days == 4:
                term._last_wpncb = (
                    'FARE KRW 300000\nTOTAL KRW 450000\n'
                    ' 1 YP 601Y 07DEC 1 ICNBKK SS1  1700  2120  /DCYP /E\n'
                    ' 2 YP 602Y 11DEC 5 BKKICN SS1  2255  0615   12DEC 6 /DCYP /E\n'
                )
                return 300000
            term._last_wpncb = (
                'FARE KRW 280000\nTOTAL KRW 430000\n'
                ' 1 YP 601Y 07DEC 1 ICNBKK SS1  1700  2120  /DCYP /E\n'
                ' 2 YP 602Y 10DEC 4 BKKICN SS1  2255  0615   11DEC 5 /DCYP /E\n'
            )
            return 280000
        t.query_date = fake_qd
        try:
            yp = {'airline': 'YP', 'origin': 'ICN', 'destination': 'BKK', 'depFlight': 'YP601', 'retFlight': 'YP602'}
            fare, detail = t.query_by_korea_dates(FakeTerm(), yp, date(2026, 12, 7), date(2026, 12, 11))
            self.assertEqual(calls, [(date(2026, 12, 7), 4), (date(2026, 12, 7), 3)])
            self.assertEqual(fare, 280000)
            self.assertIn('10DEC', detail['segments'][1])
            self.assertIn('11DEC', detail['segments'][1])
        finally:
            t.query_date = orig_qd

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

    def test_discover_last_end_dates_and_preview_dialog(self):
        import threading
        from PySide6.QtWidgets import QApplication
        qt_app = QApplication.instance() or QApplication([])
        self.assertEqual(c.parse_operating_weekdays(' 17C 2303 Y9 ICNCXR 2150 0110¥1 738 0 X236 DC /E', '7C', 2303), {0, 3, 4, 6})
        self.assertEqual(c.parse_operating_weekdays(' 1LJ 127 Y9 ICNCXR 1955 2320 738 0 25 DC /E', 'LJ', 127), {1, 4})
        self.assertEqual(c.parse_operating_weekdays(' 1KE 843 Y9 ICNTAO 1255 1340 738 0 DC /E', 'KE', 843), set(range(7)))
        today = date(2026, 11, 23)
        r_winter = c.normalize_route({'routeGroup': 'ICN-CXR', 'origin': 'ICN', 'destination': 'CXR', 'airline': 'TW',
                                      'depFlight': 'TW033', 'retFlight': 'TW034', 'days': '4', 'endDate': '2027-03-24'})
        r_summer = c.normalize_route({'routeGroup': 'ICN-CXR', 'origin': 'ICN', 'destination': 'CXR', 'airline': 'TW',
                                      'depFlight': 'TW033', 'retFlight': 'TW034', 'days': '3', 'startDate': '2027-03-31', 'endDate': '2027-09-30'})
        # 실제 TW033/034가 2027-10-27까지 열려 있는 시나리오 (동계 행은 시즌분할 보호로 기본 미체크, 하계 행은 2027-10-24로 갱신 체크)
        limit_ret = date(2027, 10, 27)
        class FakeTerm:
            mode = 'API'
            def minimize(self): pass
            def close(self): pass
            def cmd(self, txt, settle=0.25):
                if txt == 'I': return 'IGD'
                dd = txt[1:6]
                # 2026년 11~12월 또는 2027년 1~11월 복원
                mon = c.MONTHS.index(dd[2:]) + 1
                yr = 2026 if mon >= 11 and int(dd[:2]) >= 23 else (2026 if mon == 12 else 2027)
                if mon == 11 and int(dd[:2]) < 23: yr = 2027
                d = date(yr, mon, int(dd[:2]))
                if d > limit_ret:
                    return ''
                if 'ICNCXR' in txt:
                    return f' {dd} TUE ICN/Z¥9 CXR/-2\n 1TW 33 Y9 ICNCXR 2010 2355 738 0 DC /E\n'
                return f' {dd} TUE CXR/Z¥7 ICN/¥2\n 1TW 34 Y9 CXRICN 0055 0755 738 0 DC /E\n'
        orig_conn = t.Terminal.connect
        t.Terminal.connect = classmethod(lambda cls, prefer_api=True: FakeTerm())
        try:
            res = t.discover_last_end_dates([(0, r_winter), (1, r_summer)], [r_winter, r_summer], today, lambda *_a: None, threading.Event(), background=False)
            self.assertEqual(res[0]['newEnd'], '2027-10-23')
            self.assertTrue(res[0]['isEarlierSeasonSplit'])
            self.assertEqual(res[1]['newEnd'], '2027-10-24')
            self.assertFalse(res[1]['isEarlierSeasonSplit'])
            self.assertTrue(res[1]['changed'])
            dlg = app_mod.EndDatePreviewDialog(None, res)
            dlg.apply_selected()
            # 시즌분할 앞행(0번)은 자동 보호되어 미체크, 최신 시즌 행(1번)만 자동 체크 반영
            self.assertEqual(dlg.selected_updates, {1: '2027-10-24'})
            dlg.close()
            qt_app.processEvents()
        finally:
            t.Terminal.connect = orig_conn

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

    def test_updater_release_sha256_and_installer_preserve(self):
        import hashlib
        import importlib.util
        import io
        import json
        import zipfile
        import sabre_updater as u

        inst_path = Path(__file__).resolve().parent / "packaging" / "setup_installer.py"
        spec = importlib.util.spec_from_file_location("sabre_setup_installer", inst_path)
        inst = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inst)

        self.assertTrue(u.is_newer_version("v1.0.1", "v1.0.0"))
        self.assertTrue(u.is_newer_version("v1.2.0", "v1.1.9"))
        self.assertFalse(u.is_newer_version("v1.0.0", "v1.0.0"))
        self.assertFalse(u.is_newer_version("v0.9.9", "v1.0.0"))

        fake_bin = b"MZ-FAKE-SABRE-SETUP-PAYLOAD"
        good_sha = hashlib.sha256(fake_bin).hexdigest()
        release_json = json.dumps({
            "tag_name": "v1.1.0",
            "body": f"버그 수정 및 속도 개선\n\nSHA256: {good_sha}",
            "assets": [{
                "name": "SabreAutoLookup_Setup_v1.1.0.exe",
                "browser_download_url": "https://example.invalid/SabreAutoLookup_Setup_v1.1.0.exe",
                "url": "https://api.github.com/repos/KAKNAKIAK/sabre-auto-lookup/releases/assets/99",
            }],
        }).encode("utf-8")

        seen_reqs = []

        class _Resp(io.BytesIO):
            def __init__(self, data: bytes):
                super().__init__(data)
                self.headers = {"Content-Length": str(len(data))}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        def fake_urlopen(req, timeout=8.0):
            seen_reqs.append((req.full_url, dict(req.header_items())))
            if req.full_url.endswith("/releases/latest"):
                return _Resp(release_json)
            return _Resp(fake_bin)

        orig_open = u.urllib.request.urlopen
        try:
            u.urllib.request.urlopen = fake_urlopen
            rel = u.fetch_available_update("v1.0.0", cfg={"githubToken": "tok-test"})
            self.assertIsNotNone(rel)
            self.assertEqual(rel["version"], "v1.1.0")
            self.assertEqual(rel["sha256"], good_sha)

            dl = u.download_installer(rel)
            try:
                self.assertEqual(dl.read_bytes(), fake_bin)
                # 토큰이 있을 때 비공개 릴리즈 호환을 위해 asset API URL + octet-stream 헤더를 사용한다.
                self.assertEqual(seen_reqs[-1][0], "https://api.github.com/repos/KAKNAKIAK/sabre-auto-lookup/releases/assets/99")
                self.assertEqual(seen_reqs[-1][1].get("Accept"), "application/octet-stream")
                self.assertEqual(seen_reqs[-1][1].get("Authorization"), "Bearer tok-test")
            finally:
                dl.unlink(missing_ok=True)

            bad_rel = {**rel, "sha256": "0" * 64}
            with self.assertRaises(u.UpdateError):
                u.download_installer(bad_rel)
        finally:
            u.urllib.request.urlopen = orig_open

        # 셋업 인스톨러 payload 압축 해제: 기존 설정/노선은 보존, EXE는 교체
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            zpath = root / "payload.zip"
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr(inst.APP_EXE_NAME, b"NEW-EXE")
                zf.writestr("sabre-routes.json", '[{"routeGroup":"SEED"}]')
                zf.writestr("assets/sabre_icon.ico", b"ICO")

            inst_dir = root / "installed"
            inst_dir.mkdir()
            (inst_dir / inst.APP_EXE_NAME).write_bytes(b"OLD-EXE")
            (inst_dir / "sabre-routes.json").write_text('[{"routeGroup":"USER"}]', encoding="utf-8")
            (inst_dir / "sabre-config.json").write_text('{"agentId":"ME"}', encoding="utf-8")

            exe = inst.install_payload(zpath, inst_dir)
            self.assertEqual(exe.read_bytes(), b"NEW-EXE")
            self.assertIn("USER", (inst_dir / "sabre-routes.json").read_text(encoding="utf-8"))
            self.assertIn("ME", (inst_dir / "sabre-config.json").read_text(encoding="utf-8"))
            self.assertTrue((inst_dir / "assets" / "sabre_icon.ico").exists())

            fresh_dir = root / "fresh"
            inst.install_payload(zpath, fresh_dir)
            self.assertIn("SEED", (fresh_dir / "sabre-routes.json").read_text(encoding="utf-8"))
            self.assertEqual(inst._parse_update_dir(["--update", str(inst_dir)]), inst_dir.resolve())

            # 빈 노선 DB 스키마 및 동봉 예시 CSV 검증
            empty_db = root / "empty-routes.json"
            empty_db.write_text('{"schema": "sabre-routes-v1", "routes": []}\n', encoding="utf-8")
            self.assertEqual(c.load_routes(empty_db), [])
            sample_csv = Path(__file__).resolve().parent / "sabre-routes.example.csv"
            self.assertTrue(sample_csv.exists())
            self.assertGreater(len(c.import_routes_csv(sample_csv)), 0)

        # 앱 아이콘 및 도움말 > 업데이트 확인 메뉴 확인
        import sabre_app as app_mod
        from PySide6.QtWidgets import QApplication
        qt_app = QApplication.instance() or QApplication([])
        gui = app_mod.App()
        try:
            self.assertIn("항공운임 조회 (SABRE VER.)", gui.windowTitle())
            self.assertIn(u.APP_VERSION, gui.windowTitle())
            self.assertFalse(gui.windowIcon().isNull())
            help_labels = [a.text() for a in gui.help_menu.actions()]
            self.assertIn("업데이트 확인", help_labels)
            self.assertIn("사용 안내", help_labels)

            # HTML 매뉴얼(index.html) 및 참조 이미지 무결성 + 폴백 확인
            import re
            root_dir = Path(__file__).resolve().parent
            idx_file = root_dir / "index.html"
            self.assertTrue(idx_file.exists())
            html_text = idx_file.read_text(encoding="utf-8")
            srcs = re.findall(r'src="([^"]+)"', html_text)
            self.assertGreaterEqual(len(srcs), 9)
            for s in srcs:
                if s and not s.startswith(("http://", "https://")):
                    self.assertTrue((root_dir / s).exists(), f"missing manual asset: {s}")
            resolved = app_mod.resolve_manual_target("http://127.0.0.1:1/unreachable", timeout=0.2)
            self.assertTrue(resolved.startswith("file:///"))
            self.assertTrue(resolved.endswith("index.html"))
        finally:
            gui.close()
            qt_app.processEvents()

    def test_output_root_default_first_run_prompt_and_validation(self):
        import time
        from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
        import sabre_app as app_mod

        # 1) 기본 저장 경로는 G: 하드코딩이 아닌 앱 설치 폴더 내 output
        self.assertEqual(c.OUTPUT_ROOT.name, "output")
        self.assertNotIn("내 드라이브", str(c.OUTPUT_ROOT))

        qt_app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg_path = tmp / "sabre-config.json"
            routes_path = tmp / "sabre-routes.json"
            seed = [c.normalize_route({"origin": "ICN", "destination": "BKK", "airline": "ZE",
                                       "depFlight": "ZE511", "retFlight": "ZE512", "days": "3", "endDate": "2027-10-31"})]
            c.save_routes(routes_path, seed)

            # 쓰기 가능 폴더는 통과, 없는 경로(파일 하위에 폴더 생성 시도)는 실패
            ok, err = app_mod.validate_output_dir(tmp / "ok_out")
            self.assertTrue(ok, err)
            blocker = tmp / "not_a_dir"
            blocker.write_text("x", encoding="utf-8")
            bad_ok, bad_err = app_mod.validate_output_dir(blocker / "child")
            self.assertFalse(bad_ok)
            self.assertTrue(bad_err)

            orig_cfg, orig_rp, orig_dlg, orig_warn = app_mod.CONFIG_PATH, app_mod.ROUTES_PATH, app_mod.OutputPathDialog, QMessageBox.warning
            app_mod.CONFIG_PATH, app_mod.ROUTES_PATH = cfg_path, routes_path
            gui = app_mod.App()
            dialog_calls = []
            warns = []
            worker_runs = []
            next_pick = [None]

            class FakeOutDlg:
                def __init__(self, _parent, current, hint_text=None):
                    dialog_calls.append((str(current), hint_text))
                    self.result_path = next_pick[0]

                def exec(self):
                    return QDialog.DialogCode.Accepted if self.result_path else QDialog.DialogCode.Rejected

            try:
                app_mod.OutputPathDialog = FakeOutDlg
                QMessageBox.warning = staticmethod(lambda _p, title, msg: warns.append((title, msg)))
                gui.worker = lambda planned: worker_runs.append(planned)
                gui.job_entries[0][1].setChecked(True)
                gui.start_edit.setText("2026-12-01")
                gui.end_edit.setText("2026-12-05")

                # 2) 최초 미지정 + 취소 -> 조회 시작 안 함
                next_pick[0] = None
                gui.start_run()
                self.assertEqual(len(dialog_calls), 1)
                self.assertEqual(len(worker_runs), 0)

                # 3) 최초 미지정 + 확인 -> 경로 저장 후 조회 시작
                picked = tmp / "my_fares"
                next_pick[0] = str(picked)
                gui.start_run()
                for _ in range(30):
                    if worker_runs:
                        break
                    time.sleep(0.02)
                self.assertEqual(len(dialog_calls), 2)
                self.assertEqual(len(worker_runs), 1)
                self.assertTrue(app_mod.has_saved_output_root(path=cfg_path))
                self.assertEqual(app_mod.get_output_root(path=cfg_path), picked)
                gui.reset_buttons()

                # 4) 2회차 실행 -> 팝업 없이 즉시 실행
                gui.log_lines.append("이전 조회 로그\n")
                gui.start_run()
                for _ in range(30):
                    if len(worker_runs) >= 2:
                        break
                    time.sleep(0.02)
                self.assertEqual(len(dialog_calls), 2)
                self.assertEqual(len(worker_runs), 2)
                self.assertEqual(gui.log_lines, [])
                gui.reset_buttons()

                # 5) 저장된 경로가 접근 불가해진 경우 -> 조회 전 경고 후 재선택 팝업
                app_mod.save_output_root(blocker / "broken", cfg_path)
                next_pick[0] = None
                gui.start_run()
                self.assertEqual(len(warns), 1)
                self.assertEqual(len(dialog_calls), 3)
                self.assertEqual(len(worker_runs), 2)
            finally:
                app_mod.CONFIG_PATH, app_mod.ROUTES_PATH, app_mod.OutputPathDialog, QMessageBox.warning = orig_cfg, orig_rp, orig_dlg, orig_warn
                gui.close()
                qt_app.processEvents()

    def test_route_auto_backup_settings_prune_and_restore(self):
        import time
        from PySide6.QtWidgets import QApplication
        import sabre_app as app_mod

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            rp = tmp / "sabre-routes.json"
            bdir = tmp / "backups"
            cfg_path = tmp / "sabre-config.json"

            # 기본 설정 확인 (자동 백업 ON, 주기 0분=변경 시 즉시, 보관 20개)
            cur = app_mod.get_backup_settings(path=cfg_path)
            self.assertEqual(cur, {"enabled": True, "intervalMinutes": 0, "keepCount": 20})

            r1 = [c.normalize_route({"origin": "ICN", "destination": "BKK", "airline": "LJ", "depFlight": "LJ001", "retFlight": "LJ002", "days": "3", "endDate": "2027-02-26"})]
            r2 = r1 + [c.normalize_route({"origin": "ICN", "destination": "DAD", "airline": "KE", "depFlight": "KE457", "retFlight": "KE458", "days": "3", "endDate": "2027-10-31"})]
            r3 = [r2[1]]

            # 최초 저장은 이전 파일이 없으므로 백업 없음
            c.save_routes(rp, r1, backup_dir=bdir, backup_cfg=cur)
            self.assertEqual(len(c.list_route_backups(bdir)), 0)

            # 동일 내용 저장 시 중복 백업 생성 안 함
            c.save_routes(rp, r1, backup_dir=bdir, backup_cfg=cur)
            self.assertEqual(len(c.list_route_backups(bdir)), 0)

            # 변경 저장 시 직전 원본(r1) 자동 백업
            c.save_routes(rp, r2, backup_dir=bdir, backup_cfg=cur)
            bks = c.list_route_backups(bdir)
            self.assertEqual(len(bks), 1)
            self.assertEqual(bks[0]["count"], 1)

            # 주기 제한(60분) 설정 시 바로 재저장해도 추가 백업 스킵
            throttled = app_mod.save_backup_settings({"enabled": True, "intervalMinutes": 60, "keepCount": 2}, path=cfg_path)
            c.save_routes(rp, r3, backup_dir=bdir, backup_cfg=throttled)
            self.assertEqual(len(c.list_route_backups(bdir)), 1)

            # 주기 0 + 보관 개수 2개 설정 -> 초과분 자동 정리
            time.sleep(0.02)
            imm2 = app_mod.save_backup_settings({"enabled": True, "intervalMinutes": 0, "keepCount": 2}, path=cfg_path)
            c.save_routes(rp, r2, backup_dir=bdir, backup_cfg=imm2)
            time.sleep(0.02)
            c.save_routes(rp, r1, backup_dir=bdir, backup_cfg=imm2)
            bks = c.list_route_backups(bdir)
            self.assertEqual(len(bks), 2)

            # 2개 노선이 들어 있던 백업으로 복원 -> 현재 상태 안전 백업 + 복원 확인
            target_bk = next(b for b in bks if b["count"] == 2)
            restored = c.restore_route_backup(target_bk["path"], rp, bdir, keep_count=5)
            self.assertEqual(len(restored), 2)
            self.assertEqual(len(c.load_routes(rp)), 2)

            # RouteBackupDialog UI 초기화 및 설정 바인딩 확인
            qt_app = QApplication.instance() or QApplication([])
            dlg = app_mod.RouteBackupDialog(None, rp, bdir, cfg_path)
            try:
                self.assertTrue(dlg.enabled_chk.isChecked())
                self.assertEqual((dlg.interval_spin.value(), dlg.keep_spin.value()), (0, 2))
                self.assertGreaterEqual(dlg.table.rowCount(), 2)
            finally:
                dlg.close()
                qt_app.processEvents()


if __name__ == "__main__":
    unittest.main()

