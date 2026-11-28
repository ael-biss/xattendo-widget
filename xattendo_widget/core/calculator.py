"""Pure calculation helpers for Xattendo logtime, Attendo period fusion, and simulation."""

import datetime
import math
from typing import Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from xattendo_widget.constants import (
    ATTENDANCE_ROUNDING_OFFSET_SECONDS,
    CAMPUS_TIMEZONE,
    DEFAULT_PERIOD_TARGET_HOURS,
)
from xattendo_widget.models import (
    AttendanceDay,
    AttendancePeriod,
    DailyTargetProgress,
    GoalProgress,
    LinkedAccountsState,
    LocalTrackerSnapshot,
    LockPeriod,
    SessionRecord,
    WindowTotals,
)


def campus_zone() -> ZoneInfo:
    return ZoneInfo(CAMPUS_TIMEZONE)


def campus_now(now: Optional[datetime.datetime] = None) -> datetime.datetime:
    if now is None:
        return datetime.datetime.now(campus_zone())
    if now.tzinfo is None:
        return now.replace(tzinfo=campus_zone())
    return now.astimezone(campus_zone())


def campus_today(now: Optional[datetime.datetime] = None) -> datetime.date:
    return campus_now(now).date()


def format_hm(seconds: Optional[float]) -> str:
    if seconds is None:
        return '—'
    val = max(0, int(seconds))
    if val < 3600:
        return f'{val // 60}m'
    hours = val // 3600
    minutes = (val % 3600) // 60
    return f'{hours}h {minutes:02d}m'


def format_hms(seconds: Optional[float]) -> str:
    if seconds is None:
        return '--:--:--'
    val = max(0, int(seconds))
    hours = val // 3600
    minutes = (val % 3600) // 60
    secs = val % 60
    return f'{hours:02d}:{minutes:02d}:{secs:02d}'


def format_dec_hours(seconds: Optional[float]) -> str:
    if seconds is None:
        return '—'
    val = max(0.0, float(seconds))
    if val < 3600.0:
        return f'{int(val) // 60}m'
    return f'{val / 3600.0:.2f}h'


def format_compact_hours(seconds: Optional[float]) -> str:
    if seconds is None:
        return '—'
    text = format_hm(seconds)
    return text[:-4] if text.endswith(' 00m') else text


def attendo_period_bounds(
    now_dt: Optional[datetime.datetime] = None,
    start_weekday: int = 0,
) -> Tuple[datetime.date, datetime.date]:
    """Return (start_date, end_date) for the 7-day period containing now_dt starting on start_weekday (0=Mon..6=Sun)."""
    cur = campus_now(now_dt).date()
    wd = int(start_weekday) % 7
    days_since_start = (cur.weekday() - wd) % 7
    start_d = cur - datetime.timedelta(days=days_since_start)
    end_d = start_d + datetime.timedelta(days=6)
    return (start_d, end_d)


def _parse_iso_date_prefix(raw: str) -> Optional[datetime.date]:
    if not raw or len(raw.strip()) < 10:
        return None
    try:
        return datetime.date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None


def resolve_period_bounds(
    now_dt: Optional[datetime.datetime] = None,
    linked: Optional[LinkedAccountsState] = None,
    period_start_weekday: Optional[int] = None,
    cached_period_start: str = '',
    cached_period_end: str = '',
) -> Tuple[datetime.date, datetime.date]:
    """Resolve the user's active 7-day Attendo period bounds without hardcoding a global weekday."""
    cur_dt = campus_now(now_dt)
    today = cur_dt.date()

    if linked and linked.attendo_linked:
        if linked.current_period is not None:
            s = _parse_iso_date_prefix(linked.current_period.start)
            e = _parse_iso_date_prefix(linked.current_period.end)
            if s is not None and e is not None and e >= s:
                return (s, e)
        if linked.previous_period is not None:
            prev_e = _parse_iso_date_prefix(linked.previous_period.end)
            if prev_e is not None:
                next_start = prev_e + datetime.timedelta(days=1)
                while next_start + datetime.timedelta(days=6) < today:
                    next_start += datetime.timedelta(days=7)
                return (next_start, next_start + datetime.timedelta(days=6))

    if period_start_weekday is not None and not isinstance(period_start_weekday, bool) and 0 <= period_start_weekday <= 6:
        return attendo_period_bounds(cur_dt, start_weekday=period_start_weekday)

    cs = _parse_iso_date_prefix(cached_period_start)
    ce = _parse_iso_date_prefix(cached_period_end)
    if cs is not None and ce is not None and ce >= cs:
        if cs <= today <= ce:
            return (cs, ce)
        if today > ce:
            next_start = ce + datetime.timedelta(days=1)
            while next_start + datetime.timedelta(days=6) < today:
                next_start += datetime.timedelta(days=7)
            return (next_start, next_start + datetime.timedelta(days=6))
        return attendo_period_bounds(cur_dt, start_weekday=cs.weekday())

    return attendo_period_bounds(cur_dt, start_weekday=0)


def calculate_goal_progress(
    logged_seconds: Optional[float],
    daily_target_seconds: Optional[float],
) -> GoalProgress:
    """Compute progress toward daily target using 1337 Attendo's 35-minute rounding rule."""
    if daily_target_seconds is None or daily_target_seconds < 0:
        return GoalProgress(
            target_seconds=None,
            required_seconds=None,
            remaining_seconds=None,
            minutes_left=None,
            percent=None,
            reached=False,
        )

    required = max(0.0, float(daily_target_seconds) - ATTENDANCE_ROUNDING_OFFSET_SECONDS)
    if logged_seconds is None:
        return GoalProgress(
            target_seconds=float(daily_target_seconds),
            required_seconds=required,
            remaining_seconds=None,
            minutes_left=None,
            percent=None,
            reached=False,
        )

    logged = max(0.0, float(logged_seconds))
    remaining = max(0.0, required - logged)
    minutes_left = math.ceil(remaining / 60.0)
    reached = minutes_left == 0
    if reached:
        percent = 100
    elif required > 0:
        percent = min(99, max(0, math.floor(100.0 * logged / required)))
    else:
        percent = 100

    return GoalProgress(
        target_seconds=float(daily_target_seconds),
        required_seconds=required,
        remaining_seconds=remaining,
        minutes_left=minutes_left,
        percent=percent,
        reached=reached,
    )


def calculate_expected_recorded_hours(logged_seconds: Optional[float]) -> Optional[int]:
    """Compute expected integer recorded hours under the 35-minute rounding rule."""
    if logged_seconds is None or logged_seconds < 0:
        return None
    return math.floor((float(logged_seconds) + ATTENDANCE_ROUNDING_OFFSET_SECONDS) / 3600.0)


def clip_and_merge_intervals(
    intervals: Iterable[Tuple[float, Optional[float]]],
    start_ts: float,
    end_ts: float,
) -> List[Tuple[float, float]]:
    """Clip intervals to [start_ts, end_ts] and merge overlapping ranges."""
    clipped: List[Tuple[float, float]] = []
    for raw_start, raw_end in intervals:
        eff_end = end_ts if raw_end is None else min(float(raw_end), end_ts)
        lo = max(float(raw_start), start_ts)
        hi = min(eff_end, end_ts)
        if hi > lo:
            clipped.append((lo, hi))

    merged: List[Tuple[float, float]] = []
    for a, b in sorted(clipped):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def merge_period_progress(
    local_period_sec: float,
    local_today_sec: float,
    linked: Optional[LinkedAccountsState],
    fallback_target_hours: float = DEFAULT_PERIOD_TARGET_HOURS,
    default_start: str = '',
    default_end: str = '',
    today_iso: Optional[str] = None,
) -> Tuple[float, float, str, str, float, float]:
    """Fuse local session period seconds with linked Attendo period data.

    Returns (period_net_sec, target_hours, start_str, end_str, pct, left_hours).
    """
    t_iso = today_iso or campus_today().isoformat()
    target_h = max(1.0, float(fallback_target_hours or DEFAULT_PERIOD_TARGET_HOURS))
    start_str = default_start
    end_str = default_end
    net_sec = max(0.0, float(local_period_sec))

    if linked and linked.attendo_linked and linked.current_period is not None:
        cp = linked.current_period
        if linked.target_hours and linked.target_hours > 0:
            target_h = float(linked.target_hours)
        start_str = cp.start or start_str
        end_str = cp.end or end_str
        if cp.days:
            prior_sec = sum(d.hours for d in cp.days if d.date[:10] < t_iso) * 3600.0
        else:
            prior_sec = max(0.0, float(cp.total)) * 3600.0
        today_attendo_sec = max(
            float(local_today_sec),
            float(linked.attendo_recorded_today_seconds or 0.0),
        )
        fused = prior_sec + today_attendo_sec
        net_sec = max(cp.total * 3600.0, fused)

    hours = net_sec / 3600.0
    pct = min(100.0, (hours / target_h) * 100.0) if target_h > 0 else 0.0
    left_h = max(0.0, target_h - hours)
    return (net_sec, target_h, start_str, end_str, pct, left_h)


def compute_effective_today_metrics(
    local: LocalTrackerSnapshot,
    linked: Optional[LinkedAccountsState],
    now_ts: Optional[float] = None,
) -> Tuple[float, float, float]:
    """Fuse today's local session/locks with linked 42 Intra / Attendo totals.

    Returns (today_net_sec, today_gross_sec, today_locked_sec).
    """
    locked = max(0.0, float(local.today.locked_seconds))
    cur = local.current_session
    ts = now_ts if now_ts is not None else local.now_ts
    elapsed_since_sync = (
        max(0.0, min(ts - linked.fetched_at, 600.0))
        if (linked and linked.fetched_at > 0 and cur and cur.live)
        else 0.0
    )

    gross = max(0.0, float(local.today.gross_seconds))
    has_intra = bool(linked and linked.intra_linked and linked.intra_today_seconds is not None)
    if has_intra and linked is not None and linked.intra_today_seconds is not None:
        gross = max(gross, float(linked.intra_today_seconds) + elapsed_since_sync)
    elif linked and linked.attendo_linked and linked.attendo_live_seconds is not None:
        gross = max(gross, float(linked.attendo_live_seconds) + elapsed_since_sync)

    net = max(0.0, gross - locked)
    if (
        linked
        and linked.attendo_linked
        and linked.attendo_recorded_today_seconds is not None
        and not has_intra
    ):
        net = max(net, float(linked.attendo_recorded_today_seconds))
        gross = max(gross, net + locked)

    return (net, gross, locked)


def calculate_daily_average_target(
    local: LocalTrackerSnapshot,
    linked: Optional[LinkedAccountsState],
    today_net_sec: float,
    fallback_target_hours: float = DEFAULT_PERIOD_TARGET_HOURS,
    today_iso: Optional[str] = None,
) -> DailyTargetProgress:
    """Compute today's daily average target = (remaining_period_hours / remaining_days)."""
    t_iso = today_iso or campus_today().isoformat()
    today_date = datetime.date.fromisoformat(t_iso)
    target_h = max(1.0, float(fallback_target_hours or DEFAULT_PERIOD_TARGET_HOURS))

    if linked and linked.attendo_linked and linked.current_period is not None:
        cp = linked.current_period
        if linked.target_hours and linked.target_hours > 0:
            target_h = float(linked.target_hours)
        if cp.days:
            prior_days = [d for d in cp.days if d.date[:10] < t_iso]
            prior_hours = sum(d.hours for d in prior_days) if prior_days else 0.0
            prior_counted = sum(1 for d in prior_days if d.counted)
        else:
            prior_hours = max(0.0, float(cp.total))
            p_start = _parse_iso_date_prefix(cp.start)
            prior_counted = min(6, max(0, (today_date - p_start).days)) if p_start is not None else 0
        remaining_days = max(0, 7 - prior_counted)
        remaining_period_hours = max(0.0, target_h - prior_hours)
    else:
        prior_period_sec = max(0.0, float(local.period.net_seconds) - float(local.today.net_seconds))
        remaining_period_hours = max(0.0, target_h - prior_period_sec / 3600.0)
        fallback_dt = campus_now(datetime.datetime.combine(today_date, datetime.time(12, 0)))
        try:
            p_end = datetime.date.fromisoformat(local.period_end[:10]) if local.period_end else attendo_period_bounds(fallback_dt)[1]
        except ValueError:
            p_end = attendo_period_bounds(fallback_dt)[1]
        remaining_days = max(1, min(7, (p_end - today_date).days + 1))

    net_val = max(0.0, float(today_net_sec))
    if remaining_period_hours <= 0.0:
        return DailyTargetProgress(
            remaining_period_hours=0.0,
            remaining_days=remaining_days,
            daily_target_seconds=0.0,
            today_net_seconds=net_val,
            remaining_today_seconds=0.0,
            fraction=1.0,
            done=True,
        )

    denom_days = max(1, remaining_days)
    daily_target_sec = (remaining_period_hours / denom_days) * 3600.0
    rem_today = max(0.0, daily_target_sec - net_val)
    done = rem_today <= 0.0
    frac = 1.0 if done else max(0.0, min(1.0, net_val / daily_target_sec))
    return DailyTargetProgress(
        remaining_period_hours=remaining_period_hours,
        remaining_days=denom_days,
        daily_target_seconds=daily_target_sec,
        today_net_seconds=net_val,
        remaining_today_seconds=rem_today,
        fraction=frac,
        done=done,
    )


def compute_current_period_day(
    local: LocalTrackerSnapshot,
    linked: Optional[LinkedAccountsState],
    today_iso: Optional[str] = None,
) -> Tuple[int, int, bool]:
    """Return (current_day_1based, total_days=7, today_counted) for the active period."""
    t_iso = today_iso or campus_today().isoformat()
    today_date = datetime.date.fromisoformat(t_iso)
    total_days = 7

    if linked and linked.attendo_linked and linked.current_period is not None:
        cp = linked.current_period
        if cp.days:
            prior_counted = sum(1 for d in cp.days if d.date[:10] < t_iso and d.counted)
            today_counted = any(d.date[:10] == t_iso and d.counted for d in cp.days)
            current_day = max(1, min(total_days, prior_counted + 1))
            return (current_day, total_days, today_counted)
        p_start = _parse_iso_date_prefix(cp.start)
        if p_start is not None:
            current_day = max(1, min(total_days, (today_date - p_start).days + 1))
            return (current_day, total_days, False)
        return (1, total_days, False)

    try:
        p_start = (
            datetime.date.fromisoformat(local.period_start[:10])
            if local.period_start
            else attendo_period_bounds(campus_now(datetime.datetime.combine(today_date, datetime.time(12, 0))))[0]
        )
    except ValueError:
        p_start = attendo_period_bounds(campus_now(datetime.datetime.combine(today_date, datetime.time(12, 0))))[0]
    current_day = max(1, min(total_days, (today_date - p_start).days + 1))
    return (current_day, total_days, False)


def format_eta_clock(now_ts: float, remaining_seconds: float) -> str:
    """Return local campus HH:MM clock time when remaining_seconds will be reached."""
    target_dt = campus_now(datetime.datetime.fromtimestamp(now_ts, campus_zone())) + datetime.timedelta(
        seconds=max(0.0, float(remaining_seconds))
    )
    return target_dt.strftime('%H:%M')


def build_day_active_segments(
    local: LocalTrackerSnapshot,
    now_ts: Optional[float] = None,
) -> Tuple[float, float, List[Tuple[float, float]], float]:
    """Build today's unlocked active intervals [(start_ts, end_ts), ...] and timeline window."""
    ts = float(now_ts if now_ts is not None else local.now_ts)
    zone = campus_zone()
    now_dt = campus_now(datetime.datetime.fromtimestamp(ts, zone))
    day_start_dt = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = day_start_dt.timestamp()
    day_end = (day_start_dt + datetime.timedelta(days=1)).timestamp()

    # Default 08:00 -> 20:00 window; expand in 2h steps if sessions or now fall outside
    start_hour = 8
    end_hour = 20
    if now_dt.hour >= 20:
        end_hour = min(24, ((now_dt.hour // 2) + 1) * 2)

    active_segments: List[Tuple[float, float]] = []
    for sess in local.recent_sessions:
        s_end = ts if sess.live else min(float(sess.end_ts), ts)
        lo = max(float(sess.start_ts), day_start)
        hi = min(s_end, ts, day_end)
        if hi <= lo:
            continue

        s_dt = campus_now(datetime.datetime.fromtimestamp(lo, zone))
        if s_dt.hour < start_hour:
            start_hour = max(0, (s_dt.hour // 2) * 2)

        locks = clip_and_merge_intervals(
            [(float(iv[0]), (float(iv[1]) if iv[1] is not None else None)) for iv in sess.intervals],
            lo,
            hi,
        )
        cursor = lo
        for lk_a, lk_b in locks:
            if lk_a > cursor:
                active_segments.append((cursor, lk_a))
            cursor = max(cursor, lk_b)
        if hi > cursor:
            active_segments.append((cursor, hi))

    win_start = (day_start_dt + datetime.timedelta(hours=start_hour)).timestamp()
    win_end = (day_start_dt + datetime.timedelta(hours=end_hour)).timestamp()
    clipped_segs = [
        (max(a, win_start), min(b, win_end))
        for a, b in sorted(active_segments)
        if min(b, win_end) > max(a, win_start)
    ]
    return (win_start, win_end, clipped_segs, ts)


def build_simulated_local_and_linked(
    mode: str,
    now_ts: Optional[float] = None,
) -> Tuple[LocalTrackerSnapshot, LinkedAccountsState]:
    """Build deterministic simulated snapshots for --simulate active|locked|done|unlinked."""
    ts = now_ts if now_ts is not None else datetime.datetime.now().timestamp()
    cur_dt = campus_now(datetime.datetime.fromtimestamp(ts, campus_zone()))
    today = cur_dt.date()
    today_iso = today.isoformat()
    p_start, p_end = attendo_period_bounds(cur_dt)

    if mode == 'done':
        n_prior = 4
        prior_hours = 24.0
        today_net = 6 * 3600 + 42 * 60 + 18
        today_locked = 24 * 60 + 10
        period_net = 30 * 3600 + 24 * 60
        week_net = 30 * 3600 + 24 * 60
        month_net = 72 * 3600 + 15 * 60
        locked_now = False
    else:
        n_prior = 3
        prior_hours = 18.0
        # 2h 06m 11s (2.10h) -> 70% of 3.00h daily average target (12h left / 4 days)
        today_net = 2 * 3600 + 6 * 60 + 11
        today_locked = 32 * 60 + 15
        period_net = 20 * 3600 + 6 * 60 + 11 if mode != 'unlinked' else today_net
        week_net = 24 * 3600 + 10 * 60 if mode != 'unlinked' else today_net
        month_net = 68 * 3600 + 24 * 60 if mode != 'unlinked' else today_net
        locked_now = (mode == 'locked')

    if today < p_start + datetime.timedelta(days=n_prior):
        p_start = today - datetime.timedelta(days=n_prior)
        p_end = p_start + datetime.timedelta(days=6)

    today_gross = today_net + today_locked
    sess_start = ts - today_gross
    cur_sess = SessionRecord(
        host='c3r3p4.1337.ma',
        session_id='c21',
        start_ts=sess_start,
        end_ts=ts,
        live=True,
        locked_now=locked_now,
        gross_sec=today_gross,
        locked_sec=today_locked,
        net_sec=today_net,
        lock_count=3,
        intervals=[[sess_start + 1200, sess_start + 1200 + today_locked]],
    )
    locks = [
        LockPeriod(
            start=(cur_dt - datetime.timedelta(hours=1, minutes=45)).isoformat(),
            end=(cur_dt - datetime.timedelta(hours=1, minutes=30)).isoformat(),
            seconds=15 * 60,
            ongoing=False,
        ),
        LockPeriod(
            start=(cur_dt - datetime.timedelta(minutes=45)).isoformat(),
            end=(cur_dt - datetime.timedelta(minutes=27, seconds=45)).isoformat(),
            seconds=17 * 60 + 15,
            ongoing=locked_now,
        ),
    ]

    local = LocalTrackerSnapshot(
        now_ts=ts,
        current_session=cur_sess,
        today=WindowTotals(today_net, today_locked, today_gross, 1),
        period_start=p_start.isoformat(),
        period_end=p_end.isoformat(),
        period=WindowTotals(today_net, today_locked, today_gross, 1),
        week=WindowTotals(today_net, today_locked, today_gross, 1),
        month=WindowTotals(today_net, today_locked, today_gross, 1),
        today_locks=locks,
        recent_sessions=[cur_sess],
    )

    if mode == 'unlinked':
        linked = LinkedAccountsState(
            attendo_linked=False,
            attendo_error='Sign in to 1337 Attendo',
            intra_linked=False,
            intra_error='Sign in to 42 Intra',
            fetched_at=ts,
        )
        return (local, linked)

    if mode == 'done':
        prior_hours = 24.0
        cur_days = [
            AttendanceDay(date=(p_start + datetime.timedelta(days=0)).isoformat(), hours=6.0, counted=True),
            AttendanceDay(date=(p_start + datetime.timedelta(days=1)).isoformat(), hours=6.0, counted=True),
            AttendanceDay(date=(p_start + datetime.timedelta(days=2)).isoformat(), hours=6.0, counted=True),
            AttendanceDay(date=(p_start + datetime.timedelta(days=3)).isoformat(), hours=6.0, counted=True),
        ]
    else:
        prior_hours = 18.0
        cur_days = [
            AttendanceDay(date=(p_start + datetime.timedelta(days=0)).isoformat(), hours=6.0, counted=True),
            AttendanceDay(date=(p_start + datetime.timedelta(days=1)).isoformat(), hours=6.0, counted=True),
            AttendanceDay(date=(p_start + datetime.timedelta(days=2)).isoformat(), hours=6.0, counted=True),
        ]

    cur_period = AttendancePeriod(
        label='Current period',
        start=p_start.isoformat(),
        end=p_end.isoformat(),
        total=prior_hours,
        days=cur_days,
    )
    prev_period = AttendancePeriod(
        label='Previous period',
        start=(p_start - datetime.timedelta(days=7)).isoformat(),
        end=(p_start - datetime.timedelta(days=1)).isoformat(),
        total=32.0,
        days=[
            AttendanceDay(date=(p_start - datetime.timedelta(days=7 - i)).isoformat(), hours=5.0, counted=True)
            for i in range(7)
        ],
    )

    linked = LinkedAccountsState(
        attendo_linked=True,
        intra_linked=True,
        login='ael-biss',
        target_hours=30.0,
        current_period=cur_period,
        previous_period=prev_period,
        attendo_live_seconds=today_net,
        attendo_recorded_today_seconds=None,
        intra_today_seconds=today_gross,
        intra_yesterday_seconds=6 * 3600,
        intra_period_seconds=period_net,
        intra_week_seconds=week_net,
        intra_month_seconds=month_net,
        intra_daily={today_iso: today_gross},
        fetched_at=ts,
    )
    return (local, linked)
