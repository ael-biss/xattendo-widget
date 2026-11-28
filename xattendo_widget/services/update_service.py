"""Self-update service supporting GitHub Releases API and custom version.json manifests."""

from dataclasses import dataclass
import json
import os
import sys
import threading
import urllib.request
import zipfile
from typing import Callable, Optional, Tuple

from xattendo_widget import __version__
from xattendo_widget.constants import INSTALL_BIN_PATH, UPDATE_MANIFEST_URL


def parse_semver(version_str: str) -> Tuple[int, ...]:
    cleaned = (version_str or '').strip().lstrip('vV')
    parts = []
    for token in cleaned.split('.'):
        digits = ''.join(ch for ch in token if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer_version(remote: str, local: str = __version__) -> bool:
    return parse_semver(remote) > parse_semver(local)


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    download_url: str
    notes: str = ''
    mandatory: bool = True


def _trim_notes(raw: str, max_len: int = 240) -> str:
    text = (raw or '').strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + '…'


def parse_update_manifest(data: dict) -> Optional[UpdateInfo]:
    """Parse custom version.json or GitHub Releases API payload into UpdateInfo."""
    if not isinstance(data, dict):
        return None

    # Format 1: Custom version.json -> {"version": "1.1.0", "download_url": "https://..."}
    if 'version' in data and 'download_url' in data:
        ver = str(data.get('version') or '').strip()
        url = str(data.get('download_url') or '').strip()
        if not ver or not url:
            return None
        notes = _trim_notes(str(data.get('notes') or ''))
        mandatory = bool(data.get('mandatory', True))
        return UpdateInfo(version=ver, download_url=url, notes=notes, mandatory=mandatory)

    # Format 2: GitHub Releases API -> {"tag_name": "v1.1.0", "assets": [...]}
    tag = str(data.get('tag_name') or '').strip()
    assets = data.get('assets')
    if tag and isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get('name', ''))
            if name.endswith('.pyz') or name == 'xattendo-widget':
                url = str(asset.get('browser_download_url', '') or '').strip()
                if not url:
                    continue
                body = str(data.get('body') or '')
                mandatory = '[optional]' not in body.lower()
                return UpdateInfo(version=tag, download_url=url, notes=_trim_notes(body), mandatory=mandatory)
    return None


class UpdateService:
    def __init__(self, manifest_url: str = UPDATE_MANIFEST_URL) -> None:
        self.manifest_url = (manifest_url or '').strip()
        self.latest_info: Optional[UpdateInfo] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.manifest_url)

    def check_async(
        self,
        on_result: Callable[[Optional[str], Optional[str], Optional[str]], None],
    ) -> None:
        """
        Check for a newer release in a background thread.
        Calls on_result(remote_version, download_url, error_message).
        """
        if not self.is_configured:
            on_result(None, None, 'Update URL not configured')
            return

        def worker() -> None:
            try:
                info = self._fetch_manifest_info()
                if info and is_newer_version(info.version, __version__):
                    self.latest_info = info
                    on_result(info.version, info.download_url, None)
                else:
                    on_result(None, None, None)
            except Exception as exc:
                on_result(None, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def download_and_apply_async(
        self,
        download_url: str,
        on_complete: Callable[[bool, str], None],
    ) -> None:
        """Download new .pyz bundle, verify it, replace ~/.local/bin/xattendo-widget atomically."""
        def worker() -> None:
            tmp_path = INSTALL_BIN_PATH + '.tmp'
            try:
                os.makedirs(os.path.dirname(INSTALL_BIN_PATH), exist_ok=True)
                req = urllib.request.Request(
                    download_url,
                    headers={'User-Agent': f'XattendoDesktopWidget/{__version__}'},
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    payload = resp.read()

                with open(tmp_path, 'wb') as f:
                    f.write(payload)

                if not zipfile.is_zipfile(tmp_path):
                    raise ValueError('Downloaded file is not a valid widget bundle.')

                with zipfile.ZipFile(tmp_path, 'r') as zf:
                    names = zf.namelist()
                    if '__main__.py' not in names and '__main__.pyc' not in names:
                        raise ValueError('Bundle is missing entrypoint.')

                os.chmod(tmp_path, 0o755)
                os.replace(tmp_path, INSTALL_BIN_PATH)
                on_complete(True, INSTALL_BIN_PATH)
            except Exception as exc:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                on_complete(False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def restart_installed() -> None:
        if os.path.exists(INSTALL_BIN_PATH):
            os.execv(INSTALL_BIN_PATH, [INSTALL_BIN_PATH])
        else:
            os.execv(sys.executable, [sys.executable] + sys.argv)

    def _fetch_manifest_info(self) -> Optional[UpdateInfo]:
        req = urllib.request.Request(
            self.manifest_url,
            headers={
                'User-Agent': f'XattendoDesktopWidget/{__version__}',
                'Accept': 'application/vnd.github+json, application/json',
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        return parse_update_manifest(data)

    def _fetch_manifest(self) -> Tuple[Optional[str], Optional[str]]:
        info = self._fetch_manifest_info()
        if info:
            return (info.version, info.download_url)
        return (None, None)
