"""Standalone local X11 session & ft_lock tracker (modeled on live-estimate)."""

import datetime
import fcntl
import getpass
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from xattendo_widget.constants import (
    LEGACY_ARCHIVE_DB,
    LIVE_ESTIMATE_LEDGER_FILE,
    LOCK_STATE_FILE,
    SESSIONS_LEDGER_FILE,
    SESSIONS_LOCK_FILE,
    SHARED_HISTORY_DB,
)
from xattendo_widget.core.calculator import attendo_period_bounds, campus_now, campus_zone
from xattendo_widget.models import (
    LocalTrackerSnapshot,
    LockPeriod,
    SessionRecord,
    WindowTotals,
)

STALE_SESSION_TIMEOUT_SEC = 90.0


def parse_loginctl_timestamp(raw: str) -> float:
    """Parse loginctl Timestamp strings like 'Tue 2026-11-17 09:45:30 +00'."""
    text = raw.strip()
    match = re.match(r'^(.+?)\s+([+-]\d{2})(?::?(\d{2}))?$', text)
    if match:
        base, tz_h, tz_m = match.groups()
        tz_norm = f"{tz_h}{tz_m or '00'}"
        try:
            dt = datetime.datetime.strptime(f'{base} {tz_norm}', '%a %Y-%m-%d %H:%M:%S %z')
            return dt.timestamp()
        except ValueError:
            pass
    res = subprocess.run(
        ['date', '-d', text, '+%s'],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return float(res.stdout.strip())


def _query_session_props(sid: str) -> Dict[str, str]:
    try:
        res = subprocess.run(
            [
                'loginctl',
                'show-session',
                sid,
                '-p', 'Id',
                '-p', 'Name',
                '-p', 'User',
                '-p', 'Class',
                '-p', 'Type',
                '-p', 'State',
                '-p', 'Active',
                '-p', 'Timestamp',
                '-p', 'Seat',
                '-p', 'LockedHint',
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode != 0:
            return {}
        return dict(line.split('=', 1) for line in res.stdout.splitlines() if '=' in line)
    except (OSError, subprocess.SubprocessError):
        return {}


def get_current_x11_session() -> Optional[Dict[str, Any]]:
    """Return the active local graphical X11 session for the current user."""
    username = os.environ.get('USER') or os.environ.get('LOGNAME') or ''
    if not username:
        try:
            username = subprocess.check_output(['whoami'], text=True, timeout=3).strip()
        except (OSError, subprocess.SubprocessError):
            return None
    uid = os.getuid()

    candidates: List[str] = []
    try:
        seat_res = subprocess.run(
            ['loginctl', 'show-seat', 'seat0', '-p', 'ActiveSession', '--value'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if seat_res.returncode == 0 and seat_res.stdout.strip():
            candidates.append(seat_res.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        list_res = subprocess.run(
            ['loginctl', 'list-sessions', '--no-legend'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if list_res.returncode == 0:
            for line in list_res.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[2] == username and parts[0] not in candidates:
                    candidates.append(parts[0])
    except (OSError, subprocess.SubprocessError):
        pass

    for sid in candidates:
        props = _query_session_props(sid)
        if not props:
            continue
        if (
            props.get('Name') == username
            and props.get('User') == str(uid)
            and props.get('Class') == 'user'
            and props.get('Type') == 'x11'
            and props.get('State') in ('active', 'online', 'closing')
            and props.get('Timestamp')
        ):
            try:
                start_ts = parse_loginctl_timestamp(props['Timestamp'])
            except Exception:
                continue
            return {
                'host': socket.gethostname(),
                'session_id': props.get('Id', sid),
                'username': username,
                'uid': uid,
                'start_ts': start_ts,
                'state': props.get('State', 'active'),
            }
    return None


def read_seat0_lock_state(
    username: str,
    uid: int,
    session_id: str,
    state_path: Path = Path(LOCK_STATE_FILE),
) -> Tuple[bool, List[List[Optional[float]]]]:
    """Read lock state and raw intervals from /run/42-lock/seat0.json if owned by this session."""
    if not state_path.exists():
        return (False, [])
    try:
        data = json.loads(state_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return (False, [])

    if data.get('username') != username or data.get('uid') != uid:
        return (False, [])
    if data.get('session') != session_id:
        return (False, [])

    cleaned: List[List[Optional[float]]] = []
    for item in data.get('intervals') or []:
        if isinstance(item, list) and len(item) == 2 and item[0] is not None:
            start = float(item[0])
            end = float(item[1]) if item[1] is not None else None
            cleaned.append([start, end])
    return (bool(data.get('locked')), cleaned)


def merge_session_intervals(
    existing: List[List[Optional[float]]],
    incoming: List[List[Optional[float]]],
    session_start: float,
    now_ts: float,
) -> List[List[Optional[float]]]:
    """Merge lock intervals belonging to this session without losing history."""
    merged: List[List[Optional[float]]] = [
        [float(iv[0]), (float(iv[1]) if iv[1] is not None else None)]
        for iv in existing
    ]

    for s, e in incoming:
        if e is not None and e <= session_start:
            continue
        clipped_s = max(float(s), session_start)
        clipped_e = min(float(e), now_ts) if e is not None else None
        if clipped_e is not None and clipped_e <= clipped_s:
            continue

        matched = False
        for idx, (es, ee) in enumerate(merged):
            if abs(es - clipped_s) <= 1.5:
                if clipped_e is not None:
                    merged[idx][1] = max(ee, clipped_e) if ee is not None else clipped_e
                matched = True
                break
        if not matched:
            merged.append([clipped_s, clipped_e])

    merged.sort(key=lambda iv: iv[0])
    return merged


def normalize_and_sum_locks(
    intervals: List[List[Optional[float]]],
    win_start: float,
    win_end: float,
    open_fallback_end: float,
) -> Tuple[float, int, List[Tuple[float, float, bool]]]:
    """Merge overlapping lock intervals and return (locked_seconds, count, merged_list)."""
    clipped: List[Tuple[float, float, bool]] = []
    for s, e in intervals:
        is_open = e is None
        eff_end = float(e) if e is not None else open_fallback_end
        a = max(float(s), win_start)
        b = min(eff_end, win_end)
        if b > a:
            clipped.append((a, b, is_open and eff_end >= win_end))

    if not clipped:
        return (0.0, 0, [])

    clipped.sort(key=lambda item: item[0])
    merged: List[List[Any]] = [[clipped[0][0], clipped[0][1], clipped[0][2]]]
    for a, b, is_open in clipped[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
            merged[-1][2] = merged[-1][2] or is_open
        else:
            merged.append([a, b, is_open])

    total_locked = sum(b - a for a, b, _ in merged)
    return (total_locked, len(merged), [(a, b, bool(o)) for a, b, o in merged])


def compute_window_totals(
    sessions: Dict[str, Any],
    current_key: Optional[str],
    win_start: float,
    win_end: float,
    now_ts: float,
    baselines: Optional[Dict[str, Any]] = None,
) -> WindowTotals:
    """Compute (net_seconds, locked_seconds, gross_seconds, sessions) overlapping [win_start, win_end]."""
    total_gross = 0.0
    total_locked = 0.0
    count = 0

    for key, rec in sessions.items():
        s_start = float(rec['start_ts'])
        if key == current_key and not rec.get('closed'):
            s_end = now_ts
        else:
            s_end = float(rec.get('end_ts') or rec.get('last_seen') or s_start)

        a = max(s_start, win_start)
        b = min(s_end, win_end)
        if b <= a:
            continue

        count += 1
        gross = b - a
        locked, _, _ = normalize_and_sum_locks(rec.get('intervals', []), a, b, s_end)
        total_gross += gross
        total_locked += min(locked, gross)

    base_sec = 0.0
    if baselines:
        for entry in baselines.values():
            b_ts = float(entry.get('ts', 0.0))
            if win_start <= b_ts <= win_end:
                base_sec += float(entry.get('net_sec', 0.0))

    total_net = max(0.0, total_gross - total_locked) + base_sec
    return WindowTotals(
        net_seconds=total_net,
        locked_seconds=total_locked,
        gross_seconds=total_gross + base_sec,
        sessions=count,
    )


def compute_session_stats(rec: Dict[str, Any], is_current: bool, now_ts: float) -> SessionRecord:
    start_ts = float(rec['start_ts'])
    end_ts = (
        now_ts
        if (is_current and not rec.get('closed'))
        else float(rec.get('end_ts') or rec.get('last_seen') or start_ts)
    )
    gross = max(0.0, end_ts - start_ts)
    locked, lock_count, _ = normalize_and_sum_locks(rec.get('intervals', []), start_ts, end_ts, end_ts)
    locked = min(locked, gross)
    net = max(0.0, gross - locked)
    return SessionRecord(
        host=str(rec.get('host', '')),
        session_id=str(rec.get('session_id', '')),
        start_ts=start_ts,
        end_ts=end_ts,
        live=bool(is_current and not rec.get('closed')),
        locked_now=bool(is_current and rec.get('locked') and not rec.get('closed')),
        gross_sec=gross,
        locked_sec=locked,
        net_sec=net,
        lock_count=lock_count,
        intervals=list(rec.get('intervals', [])),
    )


def _read_ledger_file(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {'version': 1, 'sessions': {}}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict) and isinstance(data.get('sessions'), dict):
            return data
    except (OSError, ValueError):
        pass
    return {'version': 1, 'sessions': {}}


def _save_ledger_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def _finalize_session(rec: Dict[str, Any], end_ts: float) -> None:
    rec['closed'] = True
    rec['last_seen'] = max(float(rec.get('last_seen', end_ts)), end_ts)
    rec['end_ts'] = rec['last_seen']
    for iv in rec.get('intervals', []):
        if iv[1] is None:
            iv[1] = rec['end_ts']
    rec['locked'] = False


def _read_sqlite_day_locks(
    username: str,
    day_start: float,
    day_end: float,
    shared_db: Path,
    legacy_db: Path,
) -> List[List[Optional[float]]]:
    """Read-only query of shared/legacy SQLite lock archives for [day_start, day_end]."""
    rows: List[List[Optional[float]]] = []
    if shared_db.is_file():
        try:
            with sqlite3.connect(shared_db.resolve().as_uri() + '?mode=ro', uri=True, timeout=1) as db:
                for a, b in db.execute(
                    'SELECT start, end FROM intervals WHERE username = ? AND end > ? AND start < ? ORDER BY start',
                    (username, day_start, day_end),
                ).fetchall():
                    rows.append([float(a), float(b)])
        except (OSError, sqlite3.Error):
            pass
    if legacy_db.is_file():
        try:
            with sqlite3.connect(legacy_db.resolve().as_uri() + '?mode=ro', uri=True, timeout=1) as db:
                for a, b in db.execute(
                    'SELECT start, end FROM locks WHERE username = ?',
                    (username,),
                ).fetchall():
                    rows.append([float(a), float(b)])
        except (OSError, sqlite3.Error):
            pass
    return rows


class SessionTracker:
    """Tracks active local X11 session + ft_lock intervals and merges read-only live-estimate history."""

    def __init__(
        self,
        ledger_path: Path = Path(SESSIONS_LEDGER_FILE),
        lock_path: Path = Path(SESSIONS_LOCK_FILE),
        live_estimate_path: Path = Path(LIVE_ESTIMATE_LEDGER_FILE),
        seat0_path: Path = Path(LOCK_STATE_FILE),
        shared_history_db: Path = Path(SHARED_HISTORY_DB),
        legacy_archive_db: Path = Path(LEGACY_ARCHIVE_DB),
    ) -> None:
        self.ledger_path = ledger_path
        self.lock_path = lock_path
        self.live_estimate_path = live_estimate_path
        self.seat0_path = seat0_path
        self.shared_history_db = shared_history_db
        self.legacy_archive_db = legacy_archive_db

    def poll(self, closing: bool = False, now_ts: Optional[float] = None) -> LocalTrackerSnapshot:
        ts = now_ts if now_ts is not None else time.time()
        current = get_current_x11_session()
        current_key: Optional[str] = None

        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, 'w', encoding='utf-8') as lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                ledger = _read_ledger_file(self.ledger_path)
                sessions: Dict[str, Any] = ledger['sessions']

                if current is not None:
                    current_key = f"{current['host']}|{current['session_id']}|{int(current['start_ts'])}"

                for key, rec in list(sessions.items()):
                    if key == current_key or rec.get('closed'):
                        continue
                    same_host = current is not None and rec.get('host') == current['host']
                    stale = (ts - float(rec.get('last_seen', ts))) > STALE_SESSION_TIMEOUT_SEC
                    if same_host or stale:
                        _finalize_session(rec, float(rec.get('last_seen', ts)))

                if current is not None and current_key is not None:
                    rec = sessions.setdefault(
                        current_key,
                        {
                            'host': current['host'],
                            'session_id': current['session_id'],
                            'username': current['username'],
                            'uid': current['uid'],
                            'start_ts': current['start_ts'],
                            'last_seen': ts,
                            'end_ts': None,
                            'closed': False,
                            'locked': False,
                            'intervals': [],
                        },
                    )
                    is_locked, raw_intervals = read_seat0_lock_state(
                        current['username'],
                        current['uid'],
                        current['session_id'],
                        state_path=self.seat0_path,
                    )
                    rec['intervals'] = merge_session_intervals(
                        rec.get('intervals', []),
                        raw_intervals,
                        float(rec['start_ts']),
                        ts,
                    )
                    if not is_locked:
                        for iv in rec['intervals']:
                            if iv[1] is None:
                                iv[1] = ts
                    rec['locked'] = is_locked
                    rec['last_seen'] = ts
                    if closing or current['state'] == 'closing':
                        _finalize_session(rec, ts)

                _save_ledger_atomic(self.ledger_path, ledger)
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)

        # Read-only merge with live_estimate/sessions.json if present (never mutates live_estimate)
        merged_sessions = dict(ledger.get('sessions', {}))
        baselines = dict(ledger.get('baselines', {}))
        le_data = _read_ledger_file(self.live_estimate_path)
        for k, v in le_data.get('sessions', {}).items():
            if k not in merged_sessions:
                merged_sessions[k] = v
            elif k != current_key and float(v.get('last_seen', 0.0)) > float(merged_sessions[k].get('last_seen', 0.0)):
                merged_sessions[k] = v
        for k, v in le_data.get('baselines', {}).items():
            baselines.setdefault(k, v)

        username = (current.get('username') if current else None) or os.environ.get('USER') or getpass.getuser()
        return self._build_snapshot(
            merged_sessions,
            baselines,
            current_key,
            ts,
            username=username,
            shared_db=self.shared_history_db,
            legacy_db=self.legacy_archive_db,
        )

    @staticmethod
    def _build_snapshot(
        sessions: Dict[str, Any],
        baselines: Dict[str, Any],
        current_key: Optional[str],
        now_ts: float,
        username: Optional[str] = None,
        shared_db: Path = Path(SHARED_HISTORY_DB),
        legacy_db: Path = Path(LEGACY_ARCHIVE_DB),
    ) -> LocalTrackerSnapshot:
        zone = campus_zone()
        now_dt = campus_now(datetime.datetime.fromtimestamp(now_ts, zone))
        day_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        p_start_d, p_end_d = attendo_period_bounds(now_dt)
        period_start = datetime.datetime.combine(p_start_d, datetime.time(), zone).timestamp()
        week_start = (now_dt - datetime.timedelta(days=now_dt.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        month_start = now_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()

        cur_stats = (
            compute_session_stats(sessions[current_key], True, now_ts)
            if (current_key and current_key in sessions)
            else None
        )

        today_tot = compute_window_totals(sessions, current_key, day_start, now_ts, now_ts, baselines)
        period_tot = compute_window_totals(sessions, current_key, period_start, now_ts, now_ts, baselines)
        week_tot = compute_window_totals(sessions, current_key, week_start, now_ts, now_ts, baselines)
        month_tot = compute_window_totals(sessions, current_key, month_start, now_ts, now_ts, baselines)

        # Collect today's lock intervals across sessions + read-only SQLite archives
        today_iv: List[List[Optional[float]]] = []
        for key, rec in sessions.items():
            s_end = now_ts if (key == current_key and not rec.get('closed')) else float(rec.get('end_ts') or rec.get('last_seen') or now_ts)
            for iv_s, iv_e in rec.get('intervals', []):
                today_iv.append([iv_s, iv_e if iv_e is not None else (None if key == current_key else s_end)])
        user = username or os.environ.get('USER') or getpass.getuser()
        today_iv.extend(_read_sqlite_day_locks(user, day_start, now_ts, shared_db, legacy_db))
        total_locked_today, _, merged_locks = normalize_and_sum_locks(today_iv, day_start, now_ts, now_ts)
        today_tot = WindowTotals(
            net_seconds=max(0.0, today_tot.gross_seconds - total_locked_today),
            locked_seconds=max(today_tot.locked_seconds, total_locked_today),
            gross_seconds=today_tot.gross_seconds,
            sessions=today_tot.sessions,
        )
        today_locks = [
            LockPeriod(
                start=datetime.datetime.fromtimestamp(a, zone).isoformat(),
                end=datetime.datetime.fromtimestamp(b, zone).isoformat(),
                seconds=max(0.0, b - a),
                ongoing=is_open,
            )
            for a, b, is_open in merged_locks
        ]

        ordered = sorted(sessions.items(), key=lambda kv: float(kv[1]['start_ts']), reverse=True)
        recent = [compute_session_stats(rec, key == current_key, now_ts) for key, rec in ordered[:20]]

        return LocalTrackerSnapshot(
            now_ts=now_ts,
            current_session=cur_stats,
            today=today_tot,
            period_start=p_start_d.isoformat(),
            period_end=p_end_d.isoformat(),
            period=period_tot,
            week=week_tot,
            month=month_tot,
            today_locks=today_locks,
            recent_sessions=recent,
        )
