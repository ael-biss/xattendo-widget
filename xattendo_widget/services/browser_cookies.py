"""Pure-Python browser cookie reader for Firefox, Brave, and Chrome (zero pip dependencies)."""

import configparser
import hashlib
from http.cookiejar import Cookie, CookieJar
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from typing import Iterable, List, Optional, Tuple

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def _firefox_profiles() -> List[Path]:
    home = Path.home()
    roots = (
        Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config') / 'mozilla/firefox',
        home / '.mozilla/firefox',
        home / 'snap/firefox/common/.mozilla/firefox',
        home / '.var/app/org.mozilla.firefox/config/mozilla/firefox',
    )
    profiles: List[Path] = []
    for root in roots:
        ini = root / 'profiles.ini'
        if ini.is_file():
            cfg = configparser.ConfigParser()
            try:
                cfg.read(ini)
                sections = sorted(
                    (s for s in cfg.sections() if s.startswith('Profile')),
                    key=lambda s: cfg.getboolean(s, 'Default', fallback=False),
                    reverse=True,
                )
                for sec in sections:
                    val = cfg.get(sec, 'Path', fallback='')
                    if not val:
                        continue
                    path = Path(val).expanduser()
                    if cfg.getboolean(sec, 'IsRelative', fallback=True):
                        path = root / path
                    if path not in profiles:
                        profiles.append(path)
            except (configparser.Error, OSError):
                pass
        if root.is_dir():
            for path in root.glob('*.default*'):
                if path.is_dir() and path not in profiles:
                    profiles.append(path)
    return profiles


def _chromium_cookie_files(browser: str) -> List[Path]:
    home = Path.home()
    cfg = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config')
    if browser == 'brave':
        roots = [
            cfg / 'BraveSoftware/Brave-Browser',
            home / '.var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser',
        ]
    elif browser == 'chrome':
        roots = [
            cfg / 'google-chrome',
            cfg / 'google-chrome-beta',
            home / '.var/app/com.google.Chrome/config/google-chrome',
        ]
    else:
        roots = [
            cfg / 'chromium',
            home / 'snap/chromium/common/chromium',
        ]
    files: List[Path] = []
    for root in roots:
        for profile in [root / 'Default', *sorted(root.glob('Profile *'))]:
            for db in (profile / 'Network/Cookies', profile / 'Cookies'):
                if db.is_file():
                    files.append(db)
    return files


def _derive_chromium_key(secret: bytes) -> bytes:
    return hashlib.pbkdf2_hmac('sha1', secret, b'saltysalt', 1, 16)


def _get_keyring_secret(browser: str) -> bytes:
    """Query GNOME Keyring / SecretService for Chromium's Safe Storage password."""
    app_names = {
        'brave': ('Brave Safe Storage', 'brave'),
        'chrome': ('Chrome Safe Storage', 'chrome'),
        'chromium': ('Chromium Safe Storage', 'chromium'),
    }.get(browser, ('Chrome Safe Storage',))
    try:
        import secretstorage  # type: ignore
        bus = secretstorage.dbus_init()
        collection = secretstorage.get_default_collection(bus)
        if collection.is_locked():
            return b'peanuts'
        for item in collection.get_all_items():
            attrs = item.get_attributes()
            label = item.get_label()
            if label in app_names or attrs.get('application') in app_names:
                sec = item.get_secret()
                if sec:
                    return sec
    except Exception:
        pass
    return b'peanuts'


def decrypt_chromium_value(encrypted_value: bytes, key: bytes, db_version: int = 24) -> str:
    """Decrypt a Chromium v10/v11 AES-128-CBC cookie blob, handling v24+ 32-byte host-hash prefix."""
    if not encrypted_value:
        return ''
    prefix = encrypted_value[:3]
    if prefix not in (b'v10', b'v11'):
        return encrypted_value.decode('utf-8', errors='replace')

    ciphertext = encrypted_value[3:]
    if not ciphertext or (len(ciphertext) % 16) != 0:
        return ''

    cipher = Cipher(algorithms.AES(key), modes.CBC(b' ' * 16))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    raw = unpadder.update(padded) + unpadder.finalize()

    # Chromium DB meta version >= 24 prepends a 32-byte SHA-256 host_key digest
    if db_version >= 24 and len(raw) >= 32:
        raw = raw[32:]
    text = raw.decode('utf-8', errors='replace')
    # Reject values containing control characters or non-latin-1 characters
    if not text or any(ord(ch) < 0x20 or ord(ch) > 0x7E for ch in text):
        return ''
    return text


def _chromium_expiry_to_unix(expires_utc: int) -> Optional[int]:
    if not expires_utc:
        return None
    # Chromium stores microseconds since 1601-01-01; Unix epoch is 11644473600s later
    unix_sec = int(expires_utc / 1_000_000 - 11644473600)
    return unix_sec if unix_sec > 0 else None


def _query_sqlite_readonly(db_path: Path, query_fn):
    try:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=1)
        try:
            return query_fn(conn)
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                snap = Path(tmpdir) / db_path.name
                shutil.copy2(db_path, snap)
                wal = db_path.with_name(f'{db_path.name}-wal')
                if wal.is_file():
                    shutil.copy2(wal, snap.with_name(f'{snap.name}-wal'))
                conn = sqlite3.connect(f'file:{snap}?mode=ro', uri=True, timeout=1)
                try:
                    return query_fn(conn)
                finally:
                    conn.close()
        except (OSError, sqlite3.Error):
            return None


def _browser_order(browser_pref: str) -> Tuple[str, ...]:
    pref = (browser_pref or 'auto').strip().lower()
    if pref in ('brave', 'firefox', 'chrome'):
        return (pref,)
    return ('brave', 'firefox', 'chrome')


def _read_firefox_cookies(domain_suffixes: Iterable[str]) -> List[Cookie]:
    now = int(time.time())
    suffixes = tuple(domain_suffixes)
    found: List[Cookie] = []
    for profile in _firefox_profiles():
        db_path = profile / 'cookies.sqlite'
        if not db_path.is_file():
            continue

        def _q(conn: sqlite3.Connection):
            return conn.execute(
                'SELECT host, path, isSecure, expiry, name, value FROM moz_cookies'
            ).fetchall()

        rows = _query_sqlite_readonly(db_path, _q)
        if not rows:
            continue
        for host, path, is_sec, expiry, name, value in rows:
            clean_host = str(host or '').lstrip('.')
            if not any(clean_host == s or clean_host.endswith('.' + s) for s in suffixes):
                continue
            exp = int(expiry) if expiry else None
            if exp is not None and exp <= now:
                continue
            found.append(
                Cookie(
                    version=0,
                    name=str(name),
                    value=str(value or ''),
                    port=None,
                    port_specified=False,
                    domain=str(host),
                    domain_specified=str(host).startswith('.'),
                    domain_initial_dot=str(host).startswith('.'),
                    path=str(path or '/'),
                    path_specified=True,
                    secure=bool(is_sec),
                    expires=exp,
                    discard=exp is None,
                    comment=None,
                    comment_url=None,
                    rest={},
                )
            )
    return found


def _read_chromium_db_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
        if row and row[0] is not None:
            return int(row[0])
    except sqlite3.Error:
        pass
    return 0


def _read_chromium_cookies_by_profile(browser: str, domain_suffixes: Iterable[str]) -> List[List[Cookie]]:
    now = int(time.time())
    suffixes = tuple(domain_suffixes)
    per_profile: List[List[Cookie]] = []
    v10_key = _derive_chromium_key(b'peanuts')
    v11_key: Optional[bytes] = None

    for db_path in _chromium_cookie_files(browser):
        def _q(conn: sqlite3.Connection):
            db_ver = _read_chromium_db_version(conn)
            rows = conn.execute(
                'SELECT host_key, path, is_secure, expires_utc, name, value, encrypted_value FROM cookies'
            ).fetchall()
            return (db_ver, rows)

        res = _query_sqlite_readonly(db_path, _q)
        if not res:
            continue
        db_ver, rows = res
        profile_cookies: List[Cookie] = []
        for host, path, is_sec, exp_utc, name, plain_val, enc_val in rows:
            clean_host = str(host or '').lstrip('.')
            if not any(clean_host == s or clean_host.endswith('.' + s) for s in suffixes):
                continue
            exp = _chromium_expiry_to_unix(int(exp_utc or 0))
            if exp is not None and exp <= now:
                continue
            val = str(plain_val or '')
            if not val and enc_val:
                blob = bytes(enc_val)
                if blob.startswith(b'v11'):
                    if v11_key is None:
                        v11_key = _derive_chromium_key(_get_keyring_secret(browser))
                    key = v11_key
                else:
                    key = v10_key
                try:
                    val = decrypt_chromium_value(blob, key, db_ver)
                except Exception:
                    continue
            if not val:
                continue
            profile_cookies.append(
                Cookie(
                    version=0,
                    name=str(name),
                    value=val,
                    port=None,
                    port_specified=False,
                    domain=str(host),
                    domain_specified=str(host).startswith('.'),
                    domain_initial_dot=str(host).startswith('.'),
                    path=str(path or '/'),
                    path_specified=True,
                    secure=bool(is_sec),
                    expires=exp,
                    discard=exp is None,
                    comment=None,
                    comment_url=None,
                    rest={},
                )
            )
        if profile_cookies:
            per_profile.append(profile_cookies)
    return per_profile


def _read_chromium_cookies(browser: str, domain_suffixes: Iterable[str]) -> List[Cookie]:
    found: List[Cookie] = []
    for batch in _read_chromium_cookies_by_profile(browser, domain_suffixes):
        found.extend(batch)
    return found


def read_attendo_tokens(browser_pref: str = 'auto') -> List[str]:
    """Return unexpired Attendo student_token values across configured browsers."""
    tokens: List[str] = []
    for browser in _browser_order(browser_pref):
        cookies = (
            _read_firefox_cookies(('attendo.1337.ma',))
            if browser == 'firefox'
            else _read_chromium_cookies(browser, ('attendo.1337.ma',))
        )
        for c in sorted(cookies, key=lambda x: x.expires or float('inf'), reverse=True):
            if c.name == 'student_token' and c.value and c.value not in tokens:
                tokens.append(c.value)
    return tokens


def read_intra_cookie_jars(browser_pref: str = 'auto') -> List[CookieJar]:
    """Return one CookieJar per browser profile containing unexpired 42 Intra cookies."""
    jars: List[CookieJar] = []
    for browser in _browser_order(browser_pref):
        batches = (
            [_read_firefox_cookies(('42.fr',))]
            if browser == 'firefox'
            else _read_chromium_cookies_by_profile(browser, ('42.fr',))
        )
        for cookies in batches:
            if cookies:
                jar = CookieJar()
                for c in cookies:
                    jar.set_cookie(c)
                if len(jar):
                    jars.append(jar)
    return jars
