"""GitHub Releases 기반 세이버자동조회 자동 업데이트 도우미."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

APP_VERSION = "v1.0.2"
DEFAULT_REPO = "KAKNAKIAK/sabre-auto-lookup"
USER_AGENT = "SabreAutoLookupUpdater/1.0"
MAX_META_BYTES = 1024 * 1024
SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")
SETUP_ASSET_RE = re.compile(r"sabreautolookup.*setup.*\.exe$", re.IGNORECASE)


class UpdateError(Exception):
    """업데이트 확인 또는 다운로드 실패."""


def parse_version(value: str) -> tuple[int, ...]:
    text = str(value or "").strip().lower().lstrip("v")
    parts = [int(p) for p in re.findall(r"\d+", text)]
    return tuple(parts) or (0,)


def is_newer_version(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def resolve_github_token(cfg: dict | None = None, allow_gh_cli: bool = True) -> str:
    if isinstance(cfg, dict):
        tok = str(cfg.get("githubToken") or "").strip()
        if tok:
            return tok
    for env_key in ("SABRE_GITHUB_TOKEN", "GITHUB_TOKEN"):
        tok = os.environ.get(env_key, "").strip()
        if tok:
            return tok
    if not allow_gh_cli:
        return ""
    try:
        res = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return ""


def _api_headers(token: str = "", accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _read_bytes(url: str, headers: dict[str, str], timeout: float, limit: int = MAX_META_BYTES) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("업데이트 메타데이터 용량이 너무 큽니다.")
    return data


def _pick_setup_asset(assets: list[dict]) -> dict | None:
    for a in assets:
        if SETUP_ASSET_RE.search(str(a.get("name") or "")):
            return a
    for a in assets:
        if str(a.get("name") or "").lower().endswith(".exe"):
            return a
    return None


def _extract_sha256(release: dict, setup_asset: dict, token: str, timeout: float) -> str:
    setup_name = str(setup_asset.get("name") or "").lower()
    for a in release.get("assets") or []:
        name = str(a.get("name") or "").lower()
        if name in (f"{setup_name}.sha256", "sha256sums.txt", "latest.json"):
            url = a.get("url") if token and a.get("url") else a.get("browser_download_url")
            if not url:
                continue
            accept = "application/octet-stream" if token and a.get("url") else "*/*"
            try:
                raw = _read_bytes(str(url), _api_headers(token, accept), timeout).decode("utf-8-sig", "ignore")
                m = SHA256_RE.search(raw)
                if m:
                    return m.group(1).lower()
            except Exception:
                pass
    body = str(release.get("body") or "")
    for line in body.splitlines():
        if "sha256" in line.lower():
            m = SHA256_RE.search(line)
            if m:
                return m.group(1).lower()
    return ""


def fetch_latest_release(
    repo: str = DEFAULT_REPO,
    cfg: dict | None = None,
    timeout: float = 8.0,
) -> dict[str, str]:
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    token = resolve_github_token(cfg, allow_gh_cli=False)
    try:
        raw = _read_bytes(api_url, _api_headers(token), timeout)
    except urllib.error.HTTPError as exc:
        # 비공개 저장소인 경우 로컬 gh CLI 토큰으로 한 번 더 시도한다.
        if exc.code in (401, 403, 404) and not token:
            token = resolve_github_token(cfg, allow_gh_cli=True)
            if token:
                try:
                    raw = _read_bytes(api_url, _api_headers(token), timeout)
                except urllib.error.HTTPError as exc2:
                    if exc2.code == 404:
                        raise UpdateError("등록된 GitHub 릴리즈가 아직 없습니다.") from exc2
                    raise UpdateError(f"릴리즈 확인 실패 (HTTP {exc2.code})") from exc2
            elif exc.code == 404:
                raise UpdateError("등록된 릴리즈가 없거나 비공개 저장소 인증(githubToken / gh 로그인)이 필요합니다.") from exc
            else:
                raise UpdateError(f"릴리즈 확인 실패 (HTTP {exc.code})") from exc
        elif exc.code == 404:
            raise UpdateError("등록된 GitHub 릴리즈가 아직 없습니다.") from exc
        else:
            raise UpdateError(f"릴리즈 확인 실패 (HTTP {exc.code})") from exc
    except Exception as exc:
        raise UpdateError(f"GitHub 릴리즈를 확인하지 못했습니다: {exc}") from exc

    release = json.loads(raw.decode("utf-8-sig"))
    version = str(release.get("tag_name") or release.get("name") or "").strip()
    assets = release.get("assets") or []
    setup_asset = _pick_setup_asset(assets)
    if not version or not setup_asset:
        raise UpdateError("릴리즈에 설치 파일(Setup EXE)이 첨부되어 있지 않습니다.")

    download_url = str(setup_asset.get("browser_download_url") or "").strip()
    api_asset_url = str(setup_asset.get("url") or "").strip()
    if not download_url and not api_asset_url:
        raise UpdateError("릴리즈 설치 파일 다운로드 주소가 비어 있습니다.")

    sha256 = _extract_sha256(release, setup_asset, token, timeout)
    notes = str(release.get("body") or "").strip()
    return {
        "version": version,
        "asset_name": str(setup_asset.get("name") or "SabreAutoLookup_Setup.exe"),
        "download_url": download_url,
        "api_asset_url": api_asset_url,
        "sha256": sha256,
        "release_notes": notes,
        "token": token,
    }


def fetch_available_update(
    current_version: str = APP_VERSION,
    repo: str = DEFAULT_REPO,
    cfg: dict | None = None,
    timeout: float = 8.0,
) -> dict[str, str] | None:
    release = fetch_latest_release(repo=repo, cfg=cfg, timeout=timeout)
    return release if is_newer_version(release["version"], current_version) else None


def download_installer(
    release: dict[str, str],
    timeout: float = 180.0,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Path:
    token = str(release.get("token") or "").strip()
    use_api = bool(token and release.get("api_asset_url"))
    url = str(release["api_asset_url"] if use_api else release["download_url"])
    headers = _api_headers(token, "application/octet-stream") if use_api else {"User-Agent": USER_AGENT}

    target_dir = Path(tempfile.mkdtemp(prefix="SabreAutoLookupUpdate_"))
    filename = release.get("asset_name") or Path(urlparse(url).path).name or "SabreAutoLookup_Setup.exe"
    target_path = target_dir / filename
    digest = hashlib.sha256()

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, target_path.open("wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
    except Exception as exc:
        target_path.unlink(missing_ok=True)
        raise UpdateError(f"업데이트 설치 파일 다운로드 실패: {exc}") from exc

    expected_sha = str(release.get("sha256") or "").strip().lower()
    if expected_sha and digest.hexdigest().lower() != expected_sha:
        target_path.unlink(missing_ok=True)
        raise UpdateError("다운로드한 설치 파일의 SHA256 무결성 검증에 실패했습니다.")
    return target_path


def launch_installer(installer_path: Path, update_dir: Path | None = None) -> None:
    if not installer_path.exists():
        raise UpdateError(f"설치 파일을 찾지 못했습니다: {installer_path}")
    cmd = [str(installer_path)]
    if update_dir is not None:
        cmd += ["--update", str(update_dir)]
    subprocess.Popen(cmd, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
