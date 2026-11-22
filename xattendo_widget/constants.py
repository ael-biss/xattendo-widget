"""Application constants, paths, and Xattendo standalone defaults."""

import os
import zipfile

APP_NAME = 'Xattendo Desktop Widget'
CAMPUS_TIMEZONE = 'Africa/Casablanca'
ATTENDANCE_ROUNDING_OFFSET_SECONDS = (60 - 35) * 60  # 1500s: 35m past hour rounds up

ATTENDO_PROFILE_URL = 'https://attendo.1337.ma/students/profile'
ATTENDO_LOGIN_URL = 'https://attendo.1337.ma/students/login'
INTRA_PROFILE_URL = 'https://profile.intra.42.fr/'

LOCK_STATE_FILE = '/run/42-lock/seat0.json'
LIVE_ESTIMATE_LEDGER_FILE = os.path.expanduser('~/.local/share/live_estimate/sessions.json')
SHARED_HISTORY_DB = os.path.expanduser('~/.local/state/logged-time/history/locks.sqlite3')
LEGACY_ARCHIVE_DB = os.path.expanduser('~/.local/state/logged-time/locks.sqlite3')

# GitHub Releases API endpoint for automatic update checks
UPDATE_MANIFEST_URL = os.environ.get(
    'XATTENDO_UPDATE_URL',
    'https://api.github.com/repos/ael-biss/xattendo-widget/releases/latest',
)

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(PACKAGE_DIR)

DATA_DIR = os.path.expanduser('~/.local/share/xattendo-widget')
SESSIONS_LEDGER_FILE = os.path.join(DATA_DIR, 'sessions.json')
SESSIONS_LOCK_FILE = os.path.join(DATA_DIR, 'sessions.lock')

INSTALL_BIN_PATH = os.path.expanduser('~/.local/bin/xattendo-widget')
CONFIG_DIR = os.path.expanduser('~/.config/xattendo-widget')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')


def _resolve_assets_dir() -> str:
    """Use repo assets/ in dev mode, or extract bundled assets from .pyz into ~/.local/share/xattendo-widget/assets."""
    local_assets = os.path.join(REPO_DIR, 'assets')
    if os.path.isdir(local_assets) and os.path.exists(os.path.join(local_assets, 'xattendo.svg')):
        return local_assets

    extracted_dir = os.path.join(DATA_DIR, 'assets')
    os.makedirs(extracted_dir, exist_ok=True)

    # When running from a single-file .pyz bundle, REPO_DIR is the .pyz archive path
    if os.path.isfile(REPO_DIR) and zipfile.is_zipfile(REPO_DIR):
        with zipfile.ZipFile(REPO_DIR, 'r') as zf:
            for name in zf.namelist():
                if name.startswith('assets/') and not name.endswith('/'):
                    rel = os.path.basename(name)
                    target = os.path.join(extracted_dir, rel)
                    if not os.path.exists(target):
                        with zf.open(name) as src, open(target, 'wb') as dst:
                            dst.write(src.read())
    return extracted_dir


ASSETS_DIR = _resolve_assets_dir()
DEFAULT_ICON_PATH = os.path.join(ASSETS_DIR, 'xattendo.svg')
DONE_ICON_PATH = os.path.join(ASSETS_DIR, 'xattendo_done.svg')
ALERT_ICON_PATH = os.path.join(ASSETS_DIR, 'xattendo_alert.svg')

DEFAULT_PERIOD_TARGET_HOURS = 30.0
DEFAULT_REFRESH_INTERVAL = 120
DEFAULT_ALMOST_GOAL_MINUTES = 15
