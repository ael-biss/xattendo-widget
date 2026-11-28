"""Direct HTTPS linker for 1337 Attendo and 42 Intra (no local web server required)."""

from dataclasses import dataclass
import datetime
import getpass
from html.parser import HTMLParser
import json
import os
import re
import threading
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple
import urllib.error
from urllib.parse import quote
import urllib.request

from xattendo_widget.constants import ATTENDO_PROFILE_URL
from xattendo_widget.core.calculator import attendo_period_bounds, campus_now
from xattendo_widget.models import AttendanceDay, AttendancePeriod, LinkedAccountsState
from xattendo_widget.services.browser_cookies import read_attendo_tokens, read_intra_cookie_jars

INTRA_HOST = 'translate.intra.42.fr'
INTRA_ORIGIN = 'https://profile.intra.42.fr'
USER_AGENT = (
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36'
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PermissionError('Session redirected to login.')


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_script = False
        self.buffer: List[str] = []
        self.scripts: List[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag == 'script':
            self.in_script = True
            self.buffer = []

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'script' and self.in_script:
            self.scripts.append(''.join(self.buffer))
            self.in_script = False


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag in ('script', 'style'):
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, text: str) -> None:
        if not self.hidden and text.strip():
            self.parts.append(text.strip())


@dataclass(frozen=True)
class ParsedAttendoProfile:
    login: str
    current: Optional[AttendancePeriod]
    previous: Optional[AttendancePeriod]
    live_estimate: Optional[str]
    today_hours: Optional[float]
    target_hours: Optional[float]


def _extract_next_data(html: str) -> str:
    parser = _ScriptCollector()
    parser.feed(html)
    chunks: List[str] = []
    for script in parser.scripts:
        match = re.fullmatch(r'\s*self\.__next_f\.push\((.*)\)\s*', script, re.DOTALL)
        if not match:
            continue
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], str):
            chunks.append(payload[1])
    return ''.join(chunks)


def parse_attendo_profile_html(html: str) -> ParsedAttendoProfile:
    """Parse Next.js RSC payload and visible target from Attendo's student profile HTML."""
    data = _extract_next_data(html)
    if not data:
        data = html.replace(r'\"', '"')

    estimates = re.findall(r'"todayHoursEstimation"\s*:\s*(?:"([0-9]+:[0-9]{2})"|null)', data)
    estimate = estimates[-1] if estimates and estimates[-1] else None

    recorded = re.findall(r'"todayHours"\s*:\s*([0-9]+(?:\.[0-9]+)?|null)', data)
    today_hours = float(recorded[-1]) if recorded and recorded[-1] != 'null' else None

    logins = re.findall(r'"login"\s*:\s*"([^"\\]+)"', data)
    if not logins:
        raise ValueError('Could not identify student login in Attendo profile HTML.')
    login = logins[-1]

    decoder = json.JSONDecoder()
    raw_periods: List[Tuple[str, str, float, List[AttendanceDay]]] = []
    for match in re.finditer(r'\{\s*"weekStart"\s*:', data):
        try:
            period_obj, _ = decoder.raw_decode(data, match.start())
        except json.JSONDecodeError:
            continue
        if not isinstance(period_obj, dict):
            continue
        start = period_obj.get('weekStart')
        end = period_obj.get('weekEnd')
        total = period_obj.get('total')
        daily = period_obj.get('daily')
        if not (
            isinstance(start, str)
            and isinstance(end, str)
            and type(total) in (int, float)
            and isinstance(daily, list)
        ):
            continue
        days: List[AttendanceDay] = []
        for day_obj in daily:
            if not isinstance(day_obj, dict):
                continue
            d_str = day_obj.get('date')
            counted = day_obj.get('counted')
            hours = day_obj.get('hours', day_obj.get('hoursLogged'))
            if isinstance(d_str, str) and isinstance(counted, bool) and type(hours) in (int, float):
                days.append(AttendanceDay(date=d_str, hours=float(hours), counted=counted))
        raw_periods.append((start, end, float(total), days))

    if not raw_periods:
        raise ValueError('Could not find attendance periods in Attendo profile HTML.')

    last_counted = sum(1 for d in raw_periods[-1][3] if d.counted)
    if last_counted < 7:
        cur_raw = raw_periods[-1]
        prev_raw = raw_periods[-2] if len(raw_periods) > 1 else None
        current = AttendancePeriod('Current period', cur_raw[0], cur_raw[1], cur_raw[2], cur_raw[3])
        previous = (
            AttendancePeriod('Previous period', prev_raw[0], prev_raw[1], prev_raw[2], prev_raw[3])
            if prev_raw
            else None
        )
    else:
        prev_raw = raw_periods[-1]
        current = None
        previous = AttendancePeriod('Previous period', prev_raw[0], prev_raw[1], prev_raw[2], prev_raw[3])

    visible = _VisibleText()
    visible.feed(html)
    target_match = re.search(
        r'Attendance target\s+(\d+(?:\.\d+)?)\s*h\s+per counted-day period',
        ' '.join(visible.parts),
        re.IGNORECASE,
    )
    target = float(target_match.group(1)) if target_match else None
    if target is not None and not (0 < target < 10000):
        target = None

    return ParsedAttendoProfile(
        login=login,
        current=current,
        previous=previous,
        live_estimate=estimate,
        today_hours=today_hours,
        target_hours=target,
    )


def format_cookie_header(pairs: Iterable[Tuple[str, str]]) -> str:
    """Format (name, value) pairs into a deduplicated HTTP Cookie header string."""
    ordered: Dict[str, str] = {}
    for raw_name, raw_val in pairs:
        name = str(raw_name or '').strip()
        val = str(raw_val or '').strip()
        if not name or not val:
            continue
        ordered[name] = val
    return '; '.join(f'{k}={v}' for k, v in ordered.items())


def parse_intra_locations_json(payload: dict) -> Dict[str, float]:
    """Parse 42 Intra locations_stats.json into {YYYY-MM-DD: seconds}."""
    if not isinstance(payload, dict):
        raise ValueError('Unexpected 42 Intra location format.')
    totals: Dict[str, float] = {}
    for key, value in payload.items():
        if not isinstance(value, str):
            continue
        m = re.fullmatch(r'(\d+):([0-5]?\d):([0-5]?\d(?:\.\d+)?)', value)
        if m:
            datetime.date.fromisoformat(key)
            h, mins, secs = m.groups()
            totals[key] = int(h) * 3600.0 + int(mins) * 60.0 + float(secs)
    return totals


def _collect_attendo_cookie_headers(manual_token: str, browser_pref: str) -> List[str]:
    headers: List[str] = []
    if manual_token.strip():
        headers.append(f'student_token={manual_token.strip()}')
    env_cookie = os.environ.get('ATTENDO_COOKIE', '').strip()
    if env_cookie and env_cookie not in headers:
        headers.append(env_cookie)
    env_token = os.environ.get('ATTENDO_TOKEN', '').strip()
    if env_token:
        h = f'student_token={env_token}'
        if h not in headers:
            headers.append(h)
    for tok in read_attendo_tokens(browser_pref):
        h = f'student_token={tok}'
        if h not in headers:
            headers.append(h)
    return headers


def _fetch_attendo(manual_token: str, browser_pref: str) -> Tuple[Optional[ParsedAttendoProfile], Optional[str]]:
    headers = _collect_attendo_cookie_headers(manual_token, browser_pref)
    if not headers:
        return (None, 'Sign in to 1337 Attendo in your browser.')
    last_err = 'Sign in to 1337 Attendo.'
    for cookie_hdr in headers:
        req = urllib.request.Request(
            ATTENDO_PROFILE_URL,
            headers={
                'Accept': 'text/html,application/xhtml+xml',
                'Cookie': cookie_hdr,
                'User-Agent': 'xattendo-widget/1.0',
            },
        )
        try:
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(req, timeout=12) as resp:
                body = resp.read(8 * 1024 * 1024 + 1)
            return (parse_attendo_profile_html(body.decode('utf-8', errors='replace')), None)
        except PermissionError:
            last_err = 'Attendo session expired.'
            continue
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                last_err = 'Attendo rejected session.'
                continue
            return (None, f'Attendo HTTP {exc.code}')
        except (urllib.error.URLError, OSError):
            return (None, 'Attendo unreachable')
        except ValueError as exc:
            return (None, str(exc))
    return (None, last_err)


def _fetch_intra(
    login: str,
    manual_cookie: str,
    browser_pref: str,
) -> Tuple[Optional[Dict[str, float]], Optional[str]]:
    url = f'https://{INTRA_HOST}/users/{quote(login, safe="")}/locations_stats.json'
    common_headers = {
        'Accept': '*/*',
        'Origin': INTRA_ORIGIN,
        'Referer': f'{INTRA_ORIGIN}/',
        'User-Agent': USER_AGENT,
    }

    if manual_cookie.strip():
        req = urllib.request.Request(url, headers={**common_headers, 'Cookie': manual_cookie.strip()})
        try:
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(req, timeout=10) as resp:
                payload = json.loads(resp.read(2 * 1024 * 1024 + 1))
            return (parse_intra_locations_json(payload), None)
        except Exception:
            pass

    jars = read_intra_cookie_jars(browser_pref)
    if not jars:
        return (None, 'Sign in to 42 Intra in your browser.')

    for jar in jars:
        req = urllib.request.Request(url, headers=common_headers)
        try:
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect())
            with opener.open(req, timeout=10) as resp:
                payload = json.loads(resp.read(2 * 1024 * 1024 + 1))
            return (parse_intra_locations_json(payload), None)
        except PermissionError:
            continue
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                continue
            return (None, f'42 Intra HTTP {exc.code}')
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
            continue

    return (None, 'Sign in to 42 Intra in your browser.')


class AccountLinker:
    """Direct HTTPS account linker for 1337 Attendo and 42 Intra."""

    def sync_sync(
        self,
        browser_pref: str = 'auto',
        intra_login: str = '',
        attendo_token: str = '',
        intra_cookie: str = '',
    ) -> LinkedAccountsState:
        now_dt = campus_now()
        today = now_dt.date()
        today_iso = today.isoformat()
        yest_iso = (today - datetime.timedelta(days=1)).isoformat()

        profile, attendo_err = _fetch_attendo(attendo_token, browser_pref)
        login = (
            intra_login.strip()
            or (profile.login if profile else '')
            or os.environ.get('INTRA_LOGIN', '').strip()
            or getpass.getuser()
        )

        attendo_live_sec: Optional[float] = None
        attendo_rec_today: Optional[float] = None
        if profile:
            m = re.fullmatch(r'(\d+):([0-5]\d)', profile.live_estimate or '')
            if m:
                attendo_live_sec = int(m.group(1)) * 3600.0 + int(m.group(2)) * 60.0
            if profile.today_hours is not None:
                attendo_rec_today = profile.today_hours * 3600.0

        daily_map, intra_err = _fetch_intra(login, intra_cookie, browser_pref)

        # Compute Intra window totals
        intra_today = None
        intra_yest = None
        intra_period = None
        intra_week = None
        intra_month = None
        if daily_map is not None:
            intra_today = daily_map.get(today_iso, 0.0)
            intra_yest = daily_map.get(yest_iso, 0.0)

            p_start, p_end = attendo_period_bounds(now_dt)
            if profile and profile.current:
                try:
                    p_start = datetime.date.fromisoformat(profile.current.start[:10])
                    p_end = datetime.date.fromisoformat(profile.current.end[:10])
                except ValueError:
                    pass
            w_start = today - datetime.timedelta(days=today.weekday())
            m_start = today.replace(day=1)

            intra_period = sum(
                sec for d_str, sec in daily_map.items()
                if p_start.isoformat() <= d_str <= p_end.isoformat()
            )
            intra_week = sum(
                sec for d_str, sec in daily_map.items()
                if w_start.isoformat() <= d_str <= today_iso
            )
            intra_month = sum(
                sec for d_str, sec in daily_map.items()
                if m_start.isoformat() <= d_str <= today_iso
            )

        return LinkedAccountsState(
            attendo_linked=profile is not None,
            attendo_error=attendo_err,
            intra_linked=daily_map is not None,
            intra_error=intra_err,
            login=login,
            target_hours=profile.target_hours if profile else None,
            current_period=profile.current if profile else None,
            previous_period=profile.previous if profile else None,
            attendo_live_seconds=attendo_live_sec,
            attendo_recorded_today_seconds=attendo_rec_today,
            intra_today_seconds=intra_today,
            intra_yesterday_seconds=intra_yest,
            intra_period_seconds=intra_period,
            intra_week_seconds=intra_week,
            intra_month_seconds=intra_month,
            intra_daily=daily_map or {},
            fetched_at=time.time(),
        )

    def sync_async(
        self,
        browser_pref: str,
        intra_login: str,
        attendo_token: str,
        intra_cookie: str,
        on_result: Callable[[LinkedAccountsState], None],
    ) -> None:
        def worker() -> None:
            try:
                state = self.sync_sync(
                    browser_pref=browser_pref,
                    intra_login=intra_login,
                    attendo_token=attendo_token,
                    intra_cookie=intra_cookie,
                )
            except Exception as exc:
                state = LinkedAccountsState(
                    attendo_linked=False,
                    attendo_error=str(exc),
                    intra_linked=False,
                    intra_error=str(exc),
                    fetched_at=time.time(),
                )
            on_result(state)

        threading.Thread(target=worker, daemon=True).start()
