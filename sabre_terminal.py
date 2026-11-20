"""Sabre Red Web 탭을 Chrome 디버그 포트로 제어하고 날짜별 운임을 조회한다."""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import websocket

import sabre_core as c

PORT = 9223  # 항공자동조회(TOPAS)의 9222와 분리
LOGIN_URL = ("https://accounts.havail.sabre.com/login/agent?goto=https%3A%2F%2Fsrw.sabre.com%2Flogin%2F"
             "login.html%3Fts%3Dd14ac49-srse&force=true&useKopis=true")
PUSH_RESEND_INTERVAL = 300.0  # Okta 푸시 실패/만료 시 5분 간격 재전송
MAX_PUSH_RESENDS = 5
SESSION_EXPIRY_RE = re.compile(r"SESSION\s+EXPIRED|TIMED\s+OUT|SIGN\s+IN\s+AGAIN|NOT\s+SIGNED\s+IN|RE-?AUTH|INVALID_CREDENTIALS|세션.*만료", re.I)
FARE_PRESENT_RE = re.compile(r"(?:\b\d+-|(?:^|\n)\s*(?:FARE|TOTAL))\s*KRW\s*[\d,]+", re.I)
LONG_SELL_FAIL_RE = re.compile(r"\b(?:UC|UN|LL|HL|NO)\b|UNABLE|RESTRICTED|DOES NOT OPERATE|CHECK|FORMAT", re.I)
CHROME_PATHS = (Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"))

# 명령 직전 [role="main"] 텍스트를 기억해 두고, 그 뒤에 새로 붙은 응답만 읽는다(스크롤백 삭제도 대응).
MARK_JS = "(()=>{const m=document.querySelector('[role=\"main\"],main');window.__sfPrev=m?m.innerText:'';return !!m})()"
NEW_TEXT_JS = """(()=>{const m=document.querySelector('[role="main"],main');if(!m)return '';const cur=m.innerText||'';
const prev=window.__sfPrev||'';if(!prev)return cur;if(cur.startsWith(prev))return cur.slice(prev.length);
const tail=prev.slice(-120);const idx=tail?cur.lastIndexOf(tail):-1;return idx>=0?cur.slice(idx+tail.length):cur})()"""
FOCUS_JS = ("(()=>{const i=document.querySelector('input[name=\"cmdln\"]');if(!i)return false;i.focus();"
            "i.value='';i.dispatchEvent(new Event('input',{bubbles:true}));return true})()")
PUSH_JS = ("(()=>{const b=[...document.querySelectorAll('button,a,input[type=submit],input[type=button]')]"
           ".find(e=>/Send Push/i.test((e.innerText||e.value||'').trim()));if(b){b.click();return true}return false})()")
ARM_API_JS = """(()=>{
if(window.__sfApiArmed)return !!window.__sfTpl;
window.__sfApiArmed=true;window.__sfTpl=null;
const oOpen=XMLHttpRequest.prototype.open,oSend=XMLHttpRequest.prototype.send,oSetH=XMLHttpRequest.prototype.setRequestHeader;
XMLHttpRequest.prototype.open=function(m,u){try{this.__m=m;this.__u=String(u);this.__h={}}catch{}return oOpen.apply(this,arguments)};
XMLHttpRequest.prototype.setRequestHeader=function(k,v){try{if(this.__h)this.__h[k]=v}catch{}return oSetH.apply(this,arguments)};
XMLHttpRequest.prototype.send=function(b){
  try{
    if(this.__u&&this.__u.includes('ExecuteCommandFlow')&&typeof b==='string'&&b.includes('d.SessionContext')&&
       (b.includes('NGV://POS/SEND')||this.__u.includes('_cmd=I')||!window.__sfTpl)){
      window.__sfTpl={url:this.__u,headers:Object.assign({},this.__h),body:b};
    }
  }catch{}
  return oSend.apply(this,arguments);
};
return false})()"""
S02_MODAL_JS = """(()=>{
const d=document.querySelector('.s02-modal')||[...document.querySelectorAll('[role=dialog],[role=alertdialog],.spark-modal')]
.find(el=>/S02\\s+Error|line\\s+address/i.test(el.innerText||''));
if(!d)return '';
const btn=[...d.querySelectorAll('button')].find(b=>!b.disabled&&/^(Next|Finish|Continue|Confirm|OK)$/i.test((b.innerText||'').trim()));
if(btn){btn.click();return (btn.innerText||'').trim()}
return 'WAIT'})()"""
POPUP_JS = """(()=>{let n=0;document.querySelectorAll('[role=dialog],[role=alertdialog],.spark-modal')
.forEach(d=>{if(d.classList.contains('s02-modal')||/S02\s+Error|line\s+address|session\s+expired|timed\s+out|sign\s+in|re-?auth|세션.*만료/i.test(d.innerText||''))return;
d.querySelectorAll('button').forEach(b=>{const l=((b.getAttribute('aria-label')||'')+' '+(b.innerText||'')).trim();
if(/^(x|×|close|닫기)$/i.test(l)||/close|닫기/i.test(b.getAttribute('aria-label')||'')||(/팝업이\s*차단/i.test(d.innerText||'')&&/^확인$/.test((b.innerText||'').trim()))){b.click();n++}})});return n})()"""
SESSION_EXPIRED_JS = """(()=>/session\s+expired|timed\s+out|sign\s+in\s+again|re-?auth|세션.*만료/i.test(
(document.querySelector('[role=main],main')?.innerText||'')+' '+
[...document.querySelectorAll('[role=dialog],[role=alertdialog],.spark-modal')].map(d=>d.innerText||'').join(' ')))()"""
# shortcut: 팝업은 X/Close/닫기 버튼만 인식, 다른 형태의 팝업이 나오면 선택자 추가


class SessionExpired(RuntimeError):
    pass


def targets() -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as r:
        return json.loads(r.read().decode())


def find_target(host: str) -> dict | None:
    return next(
        (t for t in targets() if t.get("type") == "page" and urllib.parse.urlparse(t.get("url", "")).hostname == host),
        None,
    )


class Page:
    def __init__(self, target: dict):
        self.ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=20, suppress_origin=True)
        self.seq = 0
        self.send("Emulation.setFocusEmulationEnabled", {"enabled": True})  # 창을 앞으로 띄우지 않고 입력

    def send(self, method: str, params: dict | None = None) -> dict:
        self.seq += 1
        self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.seq:
                return msg

    def eval(self, expr: str):
        r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        return r.get("result", {}).get("result", {}).get("value")

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


class Terminal(Page):
    @classmethod
    def connect(cls, prefer_api: bool = True) -> "Terminal":
        try:
            target = find_target("srw.sabre.com")
        except OSError:
            target = None
        if not target:
            raise SessionExpired("Sabre 작업창이 없거나 로그아웃 상태입니다.")
        term = cls(target)
        term.mode = "CDP"
        term.long_sell = True
        term._ls_fallbacks = 0
        # S02 Error(line address) 모달은 X로 닫으면 호스트 세션이 비활성화되므로 Next -> Finish로 해제한다.
        for _ in range(6):
            if not term.eval(S02_MODAL_JS):
                break
            time.sleep(2.0)
        if term.eval(SESSION_EXPIRED_JS):
            term.close()
            raise SessionExpired("Sabre 세션 만료 모달이 표시되어 재로그인이 필요합니다.")
        term.eval(POPUP_JS)
        if not term.eval(FOCUS_JS):
            term.close()
            raise SessionExpired("Sabre 명령 입력창이 없어 재로그인이 필요합니다.")
        has_tpl = bool(term.eval(ARM_API_JS)) if prefer_api else False
        # 기존 탭 재사용 시 실제 터미널 생존(I -> IGD)과 API 템플릿 캡처를 동시에 검증한다.
        try:
            out = term.ui_cmd("I", timeout=15.0)
        except (SessionExpired, TimeoutError, RuntimeError) as exc:
            term.close()
            raise SessionExpired(f"Sabre 세션 응답 없음({exc})") from exc
        if "IGD" not in out.upper():
            term.close()
            raise SessionExpired("Sabre 세션이 만료되어 I -> IGD 응답이 없습니다.")
        if prefer_api and (has_tpl or bool(term.eval("!!window.__sfTpl"))):
            term.mode = "API"
        return term

    def minimize(self) -> None:
        try:
            win_id = self.send("Browser.getWindowForTarget").get("result", {}).get("windowId")
            if win_id is not None:
                self.send("Browser.setWindowBounds", {"windowId": win_id, "bounds": {"windowState": "minimized"}})
        except Exception:
            pass

    def api_cmd(self, text: str) -> str:
        """페이지 내부 메모리 토큰을 재사용해 NGV://POS/SEND로 직접 호스트 명령을 실행한다."""
        js = f"""(async () => {{
          const tpl = window.__sfTpl;
          if (!tpl) return {{ok:false, reason:'no_tpl'}};
          const orig = (JSON.parse(tpl.body)['d.CommandFlow']) || {{}};
          const id = '_0_' + String(Math.floor(Math.random()*1e16));
          const url = tpl.url.replace(/_cmd=[^&]+/, '_cmd=NGPOSED');
          const body = {{
            'd.CommandFlow': {{
              'd.Command': 'NGV://POS/SEND',
              'd.Data': [],
              'd.ConversationId': id,
              'd.MsgId': id,
              'd.ConvId': '_0_' + String(Math.floor(Math.random()*1e16)),
              'd.Preference': [
                {{'@secureInd':'true','d.Name':'structureOnly','d.Value':'true'}},
                {{'@secureInd':'true','d.Name':'skipPromoSpotsProcessing','d.Value':'true'}},
                {{'@secureInd':'true','d.Name':'remoteCommandBarInput','d.Value':'true'}},
                {{'@secureInd':'true','d.Name':'cf-pretty-line','d.Value':{json.dumps(text)}}},
                {{'@secureInd':'true','d.Name':'executionSource','d.Value':'UNKNOWN'}}
              ],
              'o.ExtensionPoint_Summary': {{'pos.CommandMessageRq': {{'rq': {json.dumps(text)}}}}},
              'd.RequestContext': {{'d.Module': 'sabre-ngv-commsg'}},
              'd.FlowResults': {{'d.Error': [], 'o.ExtensionPoint_Summary': {{}}}},
              'd.SessionContext': orig['d.SessionContext'] || {{'d.CurrentArea': 'a'}}
            }}
          }};
          const ac = new AbortController();
          const timer = setTimeout(() => ac.abort(), 25000);
          let r;
          try {{
            r = await fetch(url, {{
              method: 'POST', headers: tpl.headers, body: JSON.stringify(body), credentials: 'include', signal: ac.signal
            }});
          }} catch (e) {{
            return {{ok:false, reason: e && e.name === 'AbortError' ? 'timeout' : 'network'}};
          }} finally {{
            clearTimeout(timer);
          }}
          if (!r.ok) {{
            let body = '';
            try {{ body = (await r.text()).slice(0, 300); }} catch {{}}
            return {{ok:false, status:r.status, reason:'http', body}};
          }}
          const j = await r.json();
          const rcf = j['d.CommandFlow'] || {{}};
          const atk = rcf['d.SessionContext'] && rcf['d.SessionContext']['d.atk'];
          if (atk) {{
            const parsed = JSON.parse(tpl.body);
            if (parsed['d.CommandFlow'] && parsed['d.CommandFlow']['d.SessionContext']) {{
              parsed['d.CommandFlow']['d.SessionContext']['d.atk'] = atk;
              tpl.body = JSON.stringify(parsed);
            }}
          }}
          const data = rcf['d.Data'] || [];
          const texts = data.filter(x => x['d.Screen'] && x['d.Screen']['d.Text']).map(x => x['d.Screen']['d.Text']);
          const errs = (rcf['d.FlowResults'] && rcf['d.FlowResults']['d.Error']) || [];
          return {{ok:true, text:texts.join('\\n'), err:errs.length ? JSON.stringify(errs).slice(0,200) : ''}};
        }})()"""
        res = self.eval(js)
        if not isinstance(res, dict) or not res.get("ok"):
            status = res.get("status") if isinstance(res, dict) else None
            body = (res.get("body") or "") if isinstance(res, dict) else ""
            if status == 401 and SESSION_EXPIRY_RE.search(body):
                raise SessionExpired(f"Sabre API 401 인증 만료({body[:120]})")
            raise RuntimeError(f"api_failed:{status or (res.get('reason') if isinstance(res, dict) else 'none')}")
        out = res.get("text") or ""
        err = res.get("err") or ""
        if SESSION_EXPIRY_RE.search(out) or SESSION_EXPIRY_RE.search(err):
            raise SessionExpired("Sabre 세션이 만료되었습니다. 다시 로그인하세요.")
        if not out.strip() and err:
            raise RuntimeError(f"api_err:{err}")
        return out

    def ui_cmd(self, text: str, timeout: float = 30.0, settle: float = 0.25) -> str:
        """명령을 보내고 새 응답이 다 그려질 때(두 번 연속 같은 내용)까지 기다린다."""
        if self.eval(SESSION_EXPIRED_JS):
            raise SessionExpired("Sabre 세션 만료 모달이 표시되었습니다.")
        self.eval(MARK_JS)
        if not self.eval(FOCUS_JS):
            raise SessionExpired("명령 입력창이 사라졌습니다(세션 만료 또는 페이지 이동).")
        self.send("Input.insertText", {"text": text})
        for kind in ("keyDown", "keyUp"):
            self.send("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter",
                                                 "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
                                                 **({"text": "\r"} if kind == "keyDown" else {})})
        deadline, prev = time.monotonic() + timeout, None
        while time.monotonic() < deadline:
            time.sleep(settle)
            if self.eval(SESSION_EXPIRED_JS):
                raise SessionExpired("Sabre 세션 만료 모달이 표시되었습니다.")
            txt = self.eval(NEW_TEXT_JS) or ""
            if SESSION_EXPIRY_RE.search(txt):
                raise SessionExpired("Sabre 세션이 만료되었습니다. 다시 로그인하세요.")
            body = txt.replace(text, "", 1).replace("«", "").strip()
            if body and txt == prev:
                return txt
            prev = txt
        raise TimeoutError(f"응답 없음: {text}")

    def cmd(self, text: str, timeout: float = 30.0, settle: float = 0.25) -> str:
        if self.mode == "API":
            try:
                return self.api_cmd(text)
            except SessionExpired:
                raise
            except Exception:
                # 토큰 갱신 또는 구조 변경 시 UI로 1회 재캡처 후, 여전히 안 되면 CDP UI 모드로 폴백
                self.eval("window.__sfTpl=null")
                out = self.ui_cmd(text, timeout=timeout, settle=settle)
                if not self.eval("!!window.__sfTpl"):
                    self.mode = "CDP"
                return out
        return self.ui_cmd(text, timeout=timeout, settle=settle)


def find_flight(term: Terminal, command: str, airline: str, number: int, day: str, settle: float) -> dict | None:
    text = term.cmd(command, settle=settle)
    if day not in text:
        return None
    seen_lines: set[int] = set()
    for page_idx in range(4):
        rows = c.parse_availability(text)
        row = c.find_row(rows, airline, number)
        if row:
            return row
        page_lines = {r["line"] for r in rows}
        if not page_lines or (page_idx > 0 and page_lines.issubset(seen_lines)):
            return None
        seen_lines.update(page_lines)
        if page_idx == 3:
            return None
        text = term.cmd("1*", settle=settle)  # 지정편이 첫 화면에 없으면 다음 페이지
        if "NO MORE" in text.upper() or "END OF" in text.upper():
            return None
    return None


def _price_itinerary(term: Terminal, airline: str, org: str, dst: str, out_no: int, ret_no: int,
                     d1: str, d2: str, pax: int, fare_only: bool, settle: float) -> int | str:
    text = term.cmd("WPNCB", settle=settle)
    if "NO LOWER FARE" in text.upper() and not FARE_PRESENT_RE.search(text):
        text = term.cmd("WP", settle=settle)
    return c.parse_wpncb(text, airline, org, dst, out_no, ret_no, d1, d2, pax=pax, fare_only=fare_only)


def _query_long_sell(term: Terminal, route: dict, days: int, dep: date, settle: float) -> int | str:
    """가용조회 2회를 생략하고 I -> 0출국NN§0귀국NN -> WPNCB 3단계로 고속 조회한다."""
    airline, org, dst = route["airline"], route["origin"], route["destination"]
    out_no, ret_no = c.flight_no(route["depFlight"], airline), c.flight_no(route["retFlight"], airline)
    pax, req_cls, fare_only = c.route_pax(route), c.route_class(route), c.route_fare_only(route)
    cls = req_cls or "Y"
    d1, d2 = c.ddmmm(dep), c.ddmmm(dep + timedelta(days))
    if "IGD" not in term.cmd("I", settle=settle):
        return c.ERR
    ch = term.cmd(
        f"0{airline}{out_no}{cls}{d1}{org}{dst}NN{pax}§0{airline}{ret_no}{cls}{d2}{dst}{org}NN{pax}",
        settle=settle,
    )
    if not ch.strip() or LONG_SELL_FAIL_RE.search(ch):
        return c.ERR
    res = _price_itinerary(term, airline, org, dst, out_no, ret_no, d1, d2, pax, fare_only, settle)
    # 정상 운임(int)일 때만 확정하고 마감/오류는 가용조회 폴백으로 정확히 재확인한다.
    return res if isinstance(res, int) else c.ERR


def _query_via_avail(term: Terminal, route: dict, days: int, dep: date, settle: float) -> int | str:
    airline, org, dst = route["airline"], route["origin"], route["destination"]
    out_no, ret_no = c.flight_no(route["depFlight"], airline), c.flight_no(route["retFlight"], airline)
    pax, req_cls, fare_only = c.route_pax(route), c.route_class(route), c.route_fare_only(route)
    ret = dep + timedelta(days)
    if "IGD" not in term.cmd("I", settle=settle):
        return c.ERR
    for d, frm, to, no in ((dep, org, dst, out_no), (ret, dst, org, ret_no)):
        row = find_flight(term, f"1{c.ddmmm(d)}{frm}{to}¥{airline}", airline, no, c.ddmmm(d), settle)
        if row is None:
            return c.ERR
        cls = (req_cls if row["classes"].get(req_cls, 0) >= pax else None) if req_cls else c.open_class(row["classes"], pax=pax)
        if cls is None:  # 요청 클래스(또는 이코노미) 잔여석 부족이면 세그를 잡지 않고 바로 마감
            return c.SOLD
        state = c.sell_state(term.cmd(f"0{pax}{cls}{row['line']}", settle=settle), airline, no, c.ddmmm(d), pax=pax)
        if state != "ok":
            return c.SOLD if state == "sold" else c.ERR
    return _price_itinerary(term, airline, org, dst, out_no, ret_no, c.ddmmm(dep), c.ddmmm(ret), pax, fare_only, settle)


def query_once(term: Terminal, route: dict, days: int, dep: date, settle: float,
               use_long_sell: bool | None = None) -> int | str:
    try_ls = getattr(term, "long_sell", True) if use_long_sell is None else use_long_sell
    if try_ls:
        fast = _query_long_sell(term, route, days, dep, settle)
        if isinstance(fast, int):
            term._ls_fallbacks = 0
            return fast
    res = _query_via_avail(term, route, days, dep, settle)
    if try_ls and isinstance(res, int):
        # Long Sell은 거절됐는데 가용조회 Short Sell은 성공한 경우가 연속 2회면 해당 작업 동안 Long Sell을 끈다.
        fallbacks = getattr(term, "_ls_fallbacks", 0) + 1
        term._ls_fallbacks = fallbacks
        if fallbacks >= 2:
            term.long_sell = False
    return res


def query_date(term: Terminal, route: dict, days: int, dep: date) -> int | str:
    for settle in (0.25, 0.8):  # 실패하면 더 천천히 한 번 더
        try:
            result = query_once(term, route, days, dep, settle)
        except SessionExpired:
            raise
        except TimeoutError:
            # 응답 지연 시 세션이 살아있는지 즉시 확인해 만료면 재로그인으로 넘긴다.
            try:
                if "IGD" not in term.ui_cmd("I", timeout=15.0).upper():
                    raise SessionExpired("Sabre 무응답 후 세션 확인(I -> IGD) 실패")
            except SessionExpired:
                raise
            except Exception as exc:
                raise SessionExpired(f"Sabre 무응답 후 세션 단절({exc})") from exc
            result = c.ERR
        if result != c.ERR:
            return result
    return c.ERR


def _connect_or_relogin(cfg: dict | None, log, stop: threading.Event, background: bool,
                        force_relogin: bool = False) -> Terminal:
    if not force_relogin:
        try:
            term = Terminal.connect()
            log(f"연결 모드: {'내부 API 고속' if term.mode == 'API' else 'CDP 백그라운드'}")
            if background:
                term.minimize()
            return term
        except SessionExpired as exc:
            if not cfg:
                raise
            log(f"세션 만료/미연결 감지({exc}) -> 자동 재로그인을 시작합니다.")
    elif not cfg:
        raise SessionExpired("자동 재로그인 설정(cfg)이 없어 중단합니다.")
    if not launch_and_login(cfg, log, stop, force_relogin=True):
        raise SessionExpired("자동 재로그인에 실패했습니다.")
    term = Terminal.connect()
    log(f"재연결 완료 ({'내부 API 고속' if term.mode == 'API' else 'CDP 백그라운드'})")
    if background:
        term.minimize()
    return term


def run_job(route: dict, days: int, start: date, end: date, today: date, log, stop: threading.Event,
            background: bool = True, cfg: dict | None = None) -> Path | None:
    path = c.output_path(route, days, today, root=(cfg or {}).get("outputRoot"))
    basis = c.basis_text(route, days)
    term = _connect_or_relogin(cfg, log, stop, background, force_relogin=False)
    results: dict = {}
    dates = [start + timedelta(n) for n in range((end - start).days + 1)]

    def query_with_relogin(dep: date) -> int | str:
        nonlocal term
        for attempt in range(2):
            try:
                return query_date(term, route, days, dep)
            except SessionExpired as exc:
                c.save_workbook(path, basis, results)
                if not cfg or stop.is_set() or attempt >= 1:
                    raise
                log(f"{dep} 조회 중 세션 만료({exc}) -> 현재까지 {len(results)}일 저장 후 자동 재로그인")
                term.close()
                term = _connect_or_relogin(cfg, log, stop, background, force_relogin=True)
        return c.ERR

    try:
        for idx, dep in enumerate(dates, 1):
            if stop.is_set():
                break
            results[dep] = query_with_relogin(dep)
            log(f"[{idx}/{len(dates)}] {dep} {results[dep]}", (idx, len(dates)))
            if idx % 15 == 0:
                c.save_workbook(path, basis, results)
        c.save_workbook(path, basis, results)
        if stop.is_set():
            log(f"정지: {len(results)}일 저장 {path}")
            return None
        errors = [d for d, v in results.items() if v == c.ERR]  # 마감·운임은 재조회하지 않음
        if errors:
            log(f"조회오류 {len(errors)}일 1회 재조회")
            for dep in errors:
                if stop.is_set():
                    break
                results[dep] = query_with_relogin(dep)
            c.save_workbook(path, basis, results)
        try:
            term.cmd("I")
        except Exception:
            pass
        if stop.is_set():
            return None
        c.verify_workbook(path, basis, start, end)
        return path
    except SessionExpired:
        c.save_workbook(path, basis, results)
        raise
    finally:
        term.close()


def _navigate_to_login(target: dict) -> None:
    page = Page(target)
    try:
        page.send("Page.navigate", {"url": LOGIN_URL})
    finally:
        page.close()


def launch_and_login(cfg: dict, log, stop: threading.Event, force_relogin: bool = False,
                     push_resend_interval: float = PUSH_RESEND_INTERVAL,
                     max_push_resends: int = MAX_PUSH_RESENDS) -> bool:
    """디버그 크롬을 띄워 Sabre에 로그인하고 Okta 푸시 승인을 기다린다(실패/만료 시 5분 간격 최대 5회 자동 재전송)."""
    try:
        existing_srw = find_target("srw.sabre.com")
        if existing_srw and not force_relogin:
            try:
                term = Terminal.connect(prefer_api=False)
                term.close()
                log("이미 로그인된 Sabre 작업창이 정상 응답합니다(I -> IGD).")
                return True
            except SessionExpired as exc:
                # 로딩 중이거나 S02 대기 중인 정상 탭을 이탈시켜 beforeunload("사이트에서 나가시겠습니까?")를 유발하지 않도록
                # 실제 세션 만료 배너/모달이 확인된 경우에만 로그인 URL로 이동한다.
                is_expired = False
                try:
                    chk_page = Page(existing_srw)
                    try:
                        is_expired = bool(chk_page.eval(SESSION_EXPIRED_JS))
                    finally:
                        chk_page.close()
                except Exception:
                    is_expired = False
                if is_expired:
                    log(f"기존 Sabre 탭 세션 만료 감지({exc}) -> 자동 재로그인을 진행합니다.")
                    _navigate_to_login(existing_srw)
                    time.sleep(2.0)
                else:
                    log(f"기존 Sabre 작업창 준비 대기 중({exc})...")
        elif existing_srw and force_relogin:
            _navigate_to_login(existing_srw)
            time.sleep(2.0)
        elif not find_target("accounts.havail.sabre.com"):
            urllib.request.urlopen(
                urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?{LOGIN_URL}", method="PUT"),
                timeout=3,
            )
    except OSError:
        chrome = next((p for p in CHROME_PATHS if p.exists()), None)
        if not chrome:
            log("Chrome을 찾지 못했습니다.")
            return False
        profile = Path(cfg["_profile_dir"])
        profile.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [
                str(chrome),
                f"--remote-debugging-port={PORT}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-session-crashed-bubble",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                LOGIN_URL,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    filled = ever_connected = False
    push_resends = 0
    last_push_at: float | None = None
    srw_wait_logged = False
    misses = 0
    # 최초 대기 + (최대 재전송 횟수 * 재전송 간격) + 로그인 페이지 로딩 여유 120초
    overall_deadline = time.monotonic() + push_resend_interval * (max_push_resends + 1) + 120
    while time.monotonic() < overall_deadline and not stop.is_set():
        time.sleep(1.5)
        try:
            srw, login = find_target("srw.sabre.com"), find_target("accounts.havail.sabre.com")
            ever_connected, misses = True, 0
        except OSError:
            if ever_connected:
                misses += 1
                if misses >= 3:
                    log("브라우저가 닫혀 로그인을 중단했습니다.")
                    return False
            continue
        page = Page(srw or login) if (srw or login) else None
        if not page:
            continue
        try:
            if srw:
                if page.eval(SESSION_EXPIRED_JS):
                    page.send("Page.navigate", {"url": LOGIN_URL})
                    filled = False
                    srw_wait_logged = False
                    continue
                if page.eval(S02_MODAL_JS):
                    continue
                if page.eval(FOCUS_JS):
                    time.sleep(2)
                    page.eval(POPUP_JS)
                    # 재로그인 직후 구탭 오인식을 막기 위해 I -> IGD 생존 확인까지 완료한다.
                    # 단, 방금 로그인된 작업창이 아직 호스트 연결 중일 수 있으므로 로그인 페이지로 튕기지 않고 대기한다.
                    try:
                        check = Terminal.connect(prefer_api=False)
                        check.close()
                    except SessionExpired:
                        if page.eval(SESSION_EXPIRED_JS):
                            page.send("Page.navigate", {"url": LOGIN_URL})
                            filled = False
                            srw_wait_logged = False
                        elif not srw_wait_logged:
                            srw_wait_logged = True
                            log("Sabre 작업창 호스트 연결을 기다리는 중입니다...")
                        continue
                    log("Sabre 로그인 완료.")
                    return True
                continue
            body = page.eval("document.body?document.body.innerText:''") or ""
            if "Authentication failed" in body:
                log("아이디/비밀번호 오류. 계정 잠금을 막기 위해 다시 시도하지 않습니다.")
                return False
            if not filled and page.eval("!!document.querySelector('input[name=\"userId\"]')"):
                if all(cfg.get(k) for k in ("agentId", "password", "pcc")):
                    values = json.dumps([cfg["agentId"], cfg["password"], cfg["pcc"]])
                    page.eval("(()=>{const v=" + values + ";['userId','password','group'].forEach((n,i)=>{"
                              "const e=document.querySelector('input[name=\"'+n+'\"]');e.value=v[i];"
                              "e.dispatchEvent(new Event('input',{bubbles:true}))});"
                              "document.querySelector('button[name=\"login\"]').click()})()")
                    filled = True
                    log("로그인 정보를 입력했습니다.")
                else:
                    filled = True
                    log("설정 파일에 로그인 정보가 없어 브라우저에서 직접 로그인해 주세요.")
            elif last_push_at is None and page.eval(PUSH_JS):
                last_push_at = time.monotonic()
                log("Okta 푸시를 보냈습니다. 휴대폰에서 승인하세요.")
            elif last_push_at is not None and (time.monotonic() - last_push_at) >= push_resend_interval:
                if push_resends >= max_push_resends:
                    log(f"Okta 푸시 자동 재전송 {max_push_resends}회 모두 미승인되어 로그인을 중단했습니다.")
                    return False
                push_resends += 1
                if page.eval(PUSH_JS):
                    last_push_at = time.monotonic()
                    log(f"Okta 푸시 미승인/만료로 자동 재전송 ({push_resends}/{max_push_resends}). 휴대폰에서 승인하세요.")
                else:
                    # Okta 화면 자체가 만료되어 버튼이 사라진 경우 로그인 URL로 재진입해 1회 재제출 후 푸시 재전송
                    log(f"Okta 화면 만료 감지 -> 로그인 페이지 재진입 후 푸시 재전송 ({push_resends}/{max_push_resends})")
                    page.send("Page.navigate", {"url": LOGIN_URL})
                    filled = False
                    last_push_at = None
        except Exception as exc:
            log(f"로그인 진행 중 재확인: {exc}")
        finally:
            page.close()
    log("로그인 대기 시간이 지났거나 사용자가 중단했습니다.")
    return False

