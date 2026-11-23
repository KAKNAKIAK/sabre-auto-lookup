# AGENTS.md — 세이버자동조회 에이전트 운영 지침

이 문서는 `세이버자동조회` 폴더에서 작업하거나 이 프로그램을 도구로 호출하는 AI 에이전트(Codex 등)의 전용 규칙입니다.
상위 공통 정책은 `G:\내 드라이브\안티그래비티\AGENTS.md`를 UTF-8로 읽어 함께 적용합니다.

## 0. 새 세션 인계 시작 순서

1. 이 파일(`AGENTS.md`), `README.md`, `작업일지.md`의 최신 항목을 UTF-8로 읽고 현재 파일 상태를 대조합니다.
2. 코드 수정이나 조회 전 `python -X utf8 -m unittest -v test_sabre_core`와 `python -X utf8 sabre_cli.py --list`로 현재 기준 상태를 확인합니다.
3. `backup_*` 폴더는 과거 스냅샷이므로 수정하지 않습니다.

## 1. 에이전트 실행 규칙 (CLI 제어 필수, Computer Use 금지)

- AI 에이전트가 이 프로그램을 제어할 때는 **Computer Use(GUI 마우스 클릭·키보드 입력·화면 조작)로 `sabre_app.py`나 브라우저를 다루지 말고 반드시 `sabre_cli.py` CLI를 호출**합니다.
- `sabre_app.py` 및 `세이버자동조회_실행.vbs`는 사용자 직접 실행용이며, GUI 수정 검증처럼 명시적 요청이 없는 한 AI는 CLI 경로(`--list`, `--login`, `--group`, `--region`, `--all`)만 사용합니다.
- 실행 전 반드시 목록을 먼저 확인해 정확한 `routeGroup` / `region` / `days`를 사용합니다.
  ```powershell
  python -X utf8 sabre_cli.py --list
  python -X utf8 sabre_cli.py --login
  python -X utf8 sabre_cli.py --group ICN-TAO --days 2 --start 2026-12-01 --end 2026-12-31
  ```
- `sabre_cli.py`는 진행 로그를 `stderr`, 최종 결과 요약을 `stdout` JSON(`ok`, `elapsedSec`, `completed`, `failed`)으로 출력하며 종료 코드 `0`(성공) / `1`(실패)을 반환합니다.
- `sabre-config.json`의 비밀번호 등 인증정보는 절대 채팅, 로그, `작업일지.md`, 커밋에 출력하거나 복사하지 않습니다.

## 2. Sabre GDS 안전 하드 규칙

- **예약 저장·발권 명령 금지**: `E`, `ER`, `ET`, `RF`, 발권, 원격 DB 쓰기 명령은 어떤 경우에도 전송하지 않습니다. 조회는 항상 `I` → 가용(`1...`, `1*`) → 임시 판매(`01...`) → `WPNCB`(필요 시 `WP`) → 마지막 `I`로만 끝냅니다.
- **단일 실행 원칙 (병렬 금지)**: 동일 Sabre 계정으로 두 개의 프로세스를 동시에 돌리거나 `Area A~F` 병렬 호출을 구현하지 않습니다. 실측 결과 호스트가 `PREVIOUS ENTRY ACTIVE`를 반환하고 여정이 섞입니다.
- **포트 분리 유지**: 이 프로젝트의 Chrome 디버그 포트는 **`9223`**입니다. 기존 TOPAS `항공자동조회`가 사용하는 `9222` 포트와 충돌시키지 않습니다.
- **편명 임의 대체 금지**: 시트·JSON에 지정된 `출국편명`/`귀국편명`이 가용 화면(`1*` 포함)에 없으면 다른 편명이나 공동운항편으로 대체하지 않습니다.
- **이코노미 기준 유지**: `open_class()`는 `Y`가 있으면 `Y`부터 끝까지만 이코노미로 간주합니다. 비즈니스/퍼스트/프리미엄이코노미 잔여석으로 세그를 잡지 않습니다.
- **엑셀 B열 규격 유지**: B열 값은 `정수(int)`, `예약마감`, `조회불가` 3가지만 허용합니다. 사유 문자열을 추가해 후속 병합·ERP 호환성을 깨지 않습니다.
- **오류 재조회 범위**: `Error-date pass`는 정확히 `조회불가` 셀만 1회 재조회합니다. 운임 숫자와 `예약마감`(조기 마감 포함)은 재조회하지 않습니다.

## 3. 코드 수정 및 검증 규칙

- 파서·터미널·CLI를 수정한 뒤에는 반드시 아래 단위 테스트를 통과시킵니다.
  ```powershell
  $env:PYTHONUTF8 = "1"
  python -m unittest -v test_sabre_core
  ```
- `sabre_app.py` 수정 시 Tkinter 초기화 및 노선그룹 선택 연동을 확인합니다.
- Sabre 내부 API(`NGV://POS/SEND`) 응답 포맷이나 로그인 화면이 바뀐 경우 `sabre_terminal.py`의 `ARM_API_JS` / `api_cmd`와 `sabre_core.py` 파서를 함께 수정하고, CDP UI 폴백 경로도 유지합니다.
- `S02 Error` 모달(`.s02-modal`)은 `X` 버튼으로 닫지 않고 `S02_MODAL_JS`(`Next → Finish`)로 해제합니다. `POPUP_JS`에서 세션 만료·S02 모달을 제외하는 규칙을 유지합니다.
- 가용 화면 마지막 줄 끝 마침표(`K9.`, `GC.`) 파싱과 `api_cmd()`의 `d.atk` 토큰 갱신·HTTP `401` 만료 감지를 깨뜨리지 않습니다.
- Windows에서 `openpyxl.load_workbook(..., read_only=True)` 사용 시 반드시 `wb.close()`로 파일 핸들을 닫습니다.
- VBS 런처(`세이버자동조회_실행.vbs`)는 ASCII 인코딩을 유지하고 `WScript.ScriptFullName`으로 한글 경로를 동적 계산합니다.

## 4. 작업일지 및 기록

- 의미 있는 수정·검증 후에는 이 폴더의 `작업일지.md` 끝에 날짜별 항목을 추가합니다(기존 이력 보존).
- 실행하지 않은 라이브 Sabre 조회나 빌드는 미실시로 명시하며, 과거 실조회 결과를 현재 검증처럼 적지 않습니다.

## 5. Git 백업 규칙 (사용자 승인 필수)

- 원격 백업 저장소는 `origin`(`https://github.com/KAKNAKIAK/sabre-auto-lookup.git`, Private)입니다.
- 의미 있는 코드·문서 수정과 검증이 끝나면 `git status`로 변경 범위와 민감정보 제외(`sabre-config.json`, `output/`, `backup_*/` 미포함)를 먼저 확인합니다.
- **사용자 승인 없이 임의로 `git commit`·`git push` 하지 않습니다.** 변경 요약과 백업 여부를 사용자에게 확인받아 명시적 승인을 얻은 뒤 `git add` → `git commit` → `git push origin main`으로 백업합니다.
