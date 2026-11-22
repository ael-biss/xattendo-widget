"""Data models for configuration, local session tracking, and linked 42 Intra / Attendo accounts."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from xattendo_widget.constants import (
    DEFAULT_ALMOST_GOAL_MINUTES,
    DEFAULT_PERIOD_TARGET_HOURS,
    DEFAULT_REFRESH_INTERVAL,
)
from xattendo_widget.i18n import normalize_lang

VALID_PILL_MODES = ('hms', 'hours', 'period_pct')
VALID_BROWSERS = ('auto', 'brave', 'firefox', 'chrome')


@dataclass
class UserConfig:
    refresh_interval_seconds: int = DEFAULT_REFRESH_INTERVAL
    pill_display_mode: str = 'hms'     # 'hms' | 'hours' | 'period_pct'
    browser_preference: str = 'auto'   # 'auto' | 'brave' | 'firefox' | 'chrome'
    period_target_hours: float = DEFAULT_PERIOD_TARGET_HOURS
    intra_login: str = ''
    attendo_token: str = ''
    intra_cookie: str = ''
    notifications_enabled: bool = True
    goal_reached_notify: bool = True
    almost_goal_enabled: bool = True
    almost_goal_minutes: int = DEFAULT_ALMOST_GOAL_MINUTES
    widget_x: Optional[int] = None
    widget_y: Optional[int] = None
    top_bar_mode: bool = True
    top_bar_x: Optional[int] = None
    position_locked: bool = False
    language: str = 'en'

    def to_dict(self) -> dict:
        return {
            'refreshIntervalSeconds': self.refresh_interval_seconds,
            'pillDisplayMode': self.pill_display_mode,
            'browserPreference': self.browser_preference,
            'periodTargetHours': self.period_target_hours,
            'intraLogin': self.intra_login,
            'attendoToken': self.attendo_token,
            'intraCookie': self.intra_cookie,
            'notificationsEnabled': self.notifications_enabled,
            'goalReachedNotify': self.goal_reached_notify,
            'almostGoalEnabled': self.almost_goal_enabled,
            'almostGoalMinutes': self.almost_goal_minutes,
            'widgetX': self.widget_x,
            'widgetY': self.widget_y,
            'topBarMode': self.top_bar_mode,
            'topBarX': self.top_bar_x,
            'positionLocked': self.position_locked,
            'language': normalize_lang(self.language),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'UserConfig':
        try:
            refresh_sec = int(data.get('refreshIntervalSeconds', DEFAULT_REFRESH_INTERVAL))
        except (TypeError, ValueError):
            refresh_sec = DEFAULT_REFRESH_INTERVAL
        refresh_sec = max(30, min(600, refresh_sec))

        try:
            almost_min = int(data.get('almostGoalMinutes', DEFAULT_ALMOST_GOAL_MINUTES))
        except (TypeError, ValueError):
            almost_min = DEFAULT_ALMOST_GOAL_MINUTES
        almost_min = max(5, min(120, almost_min))

        try:
            target_h = float(data.get('periodTargetHours', DEFAULT_PERIOD_TARGET_HOURS))
        except (TypeError, ValueError):
            target_h = DEFAULT_PERIOD_TARGET_HOURS
        target_h = max(1.0, min(200.0, target_h))

        mode = str(data.get('pillDisplayMode', 'hms') or 'hms').strip().lower()
        if mode not in VALID_PILL_MODES:
            mode = 'hms'

        browser = str(data.get('browserPreference', 'auto') or 'auto').strip().lower()
        if browser not in VALID_BROWSERS:
            browser = 'auto'

        wx = data.get('widgetX')
        wy = data.get('widgetY')
        tbx = data.get('topBarX')

        return cls(
            refresh_interval_seconds=refresh_sec,
            pill_display_mode=mode,
            browser_preference=browser,
            period_target_hours=target_h,
            intra_login=str(data.get('intraLogin', '') or '').strip(),
            attendo_token=str(data.get('attendoToken', '') or '').strip(),
            intra_cookie=str(data.get('intraCookie', '') or '').strip(),
            notifications_enabled=bool(data.get('notificationsEnabled', True)),
            goal_reached_notify=bool(data.get('goalReachedNotify', True)),
            almost_goal_enabled=bool(data.get('almostGoalEnabled', True)),
            almost_goal_minutes=almost_min,
            widget_x=wx if isinstance(wx, int) else None,
            widget_y=wy if isinstance(wy, int) else None,
            top_bar_mode=bool(data.get('topBarMode', True)),
            top_bar_x=tbx if isinstance(tbx, int) else None,
            position_locked=bool(data.get('positionLocked', False)),
            language=normalize_lang(data.get('language', 'en')),
        )


@dataclass(frozen=True)
class LockPeriod:
    start: str
    end: str
    seconds: float
    ongoing: bool = False


@dataclass(frozen=True)
class AttendanceDay:
    date: str
    hours: float
    counted: bool


@dataclass(frozen=True)
class AttendancePeriod:
    label: str
    start: str
    end: str
    total: float
    days: List[AttendanceDay] = field(default_factory=list)

    @property
    def counted_days(self) -> int:
        return sum(1 for d in self.days if d.counted)


@dataclass(frozen=True)
class AttendanceGoal:
    target_seconds: float
    remaining_seconds: float
    remaining_days: int
    daily_seconds: Optional[float]


@dataclass(frozen=True)
class GoalProgress:
    target_seconds: Optional[float]
    required_seconds: Optional[float]
    remaining_seconds: Optional[float]
    minutes_left: Optional[int]
    percent: Optional[int]
    reached: bool


@dataclass(frozen=True)
class DailyTargetProgress:
    remaining_period_hours: float
    remaining_days: int
    daily_target_seconds: float
    today_net_seconds: float
    remaining_today_seconds: float
    fraction: float
    done: bool


@dataclass(frozen=True)
class SessionRecord:
    host: str
    session_id: str
    start_ts: float
    end_ts: float
    live: bool
    locked_now: bool
    gross_sec: float
    locked_sec: float
    net_sec: float
    lock_count: int
    intervals: List[List[Optional[float]]] = field(default_factory=list)


@dataclass(frozen=True)
class WindowTotals:
    net_seconds: float
    locked_seconds: float
    gross_seconds: float
    sessions: int


@dataclass
class LocalTrackerSnapshot:
    now_ts: float
    current_session: Optional[SessionRecord]
    today: WindowTotals
    period_start: str
    period_end: str
    period: WindowTotals
    week: WindowTotals
    month: WindowTotals
    today_locks: List[LockPeriod] = field(default_factory=list)
    recent_sessions: List[SessionRecord] = field(default_factory=list)


@dataclass
class LinkedAccountsState:
    attendo_linked: bool = False
    attendo_error: Optional[str] = None
    intra_linked: bool = False
    intra_error: Optional[str] = None
    login: Optional[str] = None
    target_hours: Optional[float] = None
    current_period: Optional[AttendancePeriod] = None
    previous_period: Optional[AttendancePeriod] = None
    attendo_live_seconds: Optional[float] = None
    attendo_recorded_today_seconds: Optional[float] = None
    intra_today_seconds: Optional[float] = None
    intra_yesterday_seconds: Optional[float] = None
    intra_period_seconds: Optional[float] = None
    intra_week_seconds: Optional[float] = None
    intra_month_seconds: Optional[float] = None
    intra_daily: Dict[str, float] = field(default_factory=dict)
    fetched_at: float = 0.0
