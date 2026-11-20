"""실제 Sabre 화면 텍스트(2026-11-19 에고 라이트 실측)로 판정 로직을 점검한다."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

import sabre_core as c
import sabre_cli as cli
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
                    return " 1 CA 440Y 01DEC 2 ICNCKG SS1" if len(sent) < 4 else " 2 CA 439Y 04DEC 5 CKGICN SS1"
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
        r = c.normalize_route({"region": "칭다오", "origin": "icn", "destination": "tao", "airline": "ke",
                               "depFlight": "ke 843", "retFlight": "KE844", "days": "3, 2", "endDate": "2027-10-31"})
        self.assertEqual(r["days"], [2, 3])
        self.assertEqual(r["routeGroup"], "ICN-TAO")
        r2 = c.normalize_route({"routeGroup": "icn-dad_pm", "region": "다낭", "origin": "ICN", "destination": "DAD",
                                "airline": "KE", "depFlight": "KE457", "retFlight": "KE458", "days": "3", "endDate": "2027-10-31"})
        self.assertEqual(r2["routeGroup"], "ICN-DAD_PM")
        grouped = c.group_routes([r, r2, {**r2, "enabled": False}])
        self.assertEqual(list(grouped.keys()), ["ICN-TAO", "ICN-DAD_PM"])
        self.assertEqual(len(grouped["ICN-DAD_PM"]), 1)
        with self.assertRaises(ValueError):
            c.normalize_route({"region": "x", "days": ""})

    def test_cli_select_jobs_and_summary(self):
        routes = c.load_routes(Path(__file__).resolve().parent / "sabre-routes.json")
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


if __name__ == "__main__":
    unittest.main()

