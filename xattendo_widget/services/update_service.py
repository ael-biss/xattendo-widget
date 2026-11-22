"""Self-update service supporting GitHub Releases API and custom version.json manifests."""

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


class UpdateService:
    def __init__(self, manifest_url: str = UPDATE_MANIFEST_URL) -> None:
        self.manifest_url = (manifest_url or '').strip()

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
                version, download_url = self._fetch_manifest()
                if version and download_url and is_newer_version(version, __version__):
                    on_result(version, download_url, None)
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

    def _fetch_manifest(self) -> Tuple[Optional[str], Optional[str]]:
        req = urllib.request.Request(
            self.manifest_url,
            headers={
                'User-Agent': f'XattendoDesktopWidget/{__version__}',
                'Accept': 'application/vnd.github+json, application/json',
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        if not isinstance(data, dict):
            return (None, None)

        # Format 1: Custom version.json -> {"version": "1.1.0", "download_url": "https://..."}
        if 'version' in data and 'download_url' in data:
            return (str(data['version']), str(data['download_url']))

        # Format 2: GitHub Releases API -> {"tag_name": "v1.1.0", "assets": [...]}
        tag = data.get('tag_name')
        assets = data.get('assets')
        if tag and isinstance(assets, list):
            for asset in assets:
                name = str(asset.get('name', ''))
                if name.endswith('.pyz') or name == 'xattendo-widget':
                    return (str(tag), str(asset.get('browser_download_url', '')))
        return (None, None)
