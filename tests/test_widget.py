"""Automated headless unit tests for standalone Xattendo Desktop Widget."""

import ctypes
import datetime
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from xattendo_widget.constants import ALERT_ICON_PATH, DEFAULT_ICON_PATH, DONE_ICON_PATH
from xattendo_widget.core.calculator import (
    attendo_period_bounds,
    build_day_active_segments,
    build_simulated_local_and_linked,
    calculate_daily_average_target,
    calculate_expected_recorded_hours,
    calculate_goal_progress,
    campus_today,
    clip_and_merge_intervals,
    compute_effective_today_metrics,
    format_compact_hours,
    format_dec_hours,
    format_eta_clock,
    format_hm,
    format_hms,
    merge_period_progress,
)
from xattendo_widget.i18n import STRINGS, format_date, is_rtl, normalize_lang, tr
from xattendo_widget.models import UserConfig
from xattendo_widget.services.account_linker import (
    parse_attendo_profile_html,
    parse_intra_locations_json,
)
from xattendo_widget.services.browser_cookies import (
    _derive_chromium_key,
    _read_chromium_db_version,
    decrypt_chromium_value,
)
from xattendo_widget.services.session_tracker import (
    SessionTracker,
    compute_session_stats,
    compute_window_totals,
    merge_session_intervals,
    normalize_and_sum_locks,
)
from xattendo_widget.services.update_service import is_newer_version, parse_semver
from xattendo_widget.services.x11_topbar import (
    XI_RAW_BUTTON_PRESS,
    XI_RAW_BUTTON_RELEASE,
    XI_RAW_MOTION,
    XEvent,
    XGenericEventCookie,
    XIRawEvent,
    set_xi_mask,
)


def _encrypt_chromium_cookie(plaintext: bytes, secret: bytes = b'peanuts') -> bytes:
    key = _derive_chromium_key(secret)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(b' ' * 16))
    enc = cipher.encryptor()
    return b'v10' + enc.update(padded) + enc.finalize()


class TestXattendoWidget(unittest.TestCase):
    def test_assets_exist_and_palettes_distinct(self):
        for path in (DEFAULT_ICON_PATH, DONE_ICON_PATH, ALERT_ICON_PATH):
            self.assertTrue(os.path.exists(path), f'{path} missing')

        with open(DEFAULT_ICON_PATH, 'r', encoding='utf-8') as f:
            default_svg = f.read()
        with open(DONE_ICON_PATH, 'r', encoding='utf-8') as f:
            done_svg = f.read()
        with open(ALERT_ICON_PATH, 'r', encoding='utf-8') as f:
            alert_svg = f.read()

        self.assertIn('#3b82f6', default_svg)
        self.assertIn('#10b981', done_svg)
        self.assertNotIn('#3b82f6', done_svg)
        self.assertIn('#ef4444', alert_svg)
        self.assertNotIn('#3b82f6', alert_svg)

    def test_duration_formatting(self):
        self.assertEqual(format_hm(None), '—')
        self.assertEqual(format_hm(5 * 3600 + 12 * 60 + 45), '5h 12m')
        self.assertEqual(format_dec_hours(3 * 3600 + 36 * 60), '3.60h')
        self.assertEqual(format_compact_hours(7 * 3600), '7h')
        self.assertEqual(format_hms(None), '--:--:--')
        self.assertEqual(format_hms(3661), '01:01:01')

    def test_chromium_cookie_decryption_v24_and_legacy(self):
        key = _derive_chromium_key(b'peanuts')
        # Legacy db_version < 24
        blob_v20 = _encrypt_chromium_cookie(b'my_secret_token')
        self.assertEqual(decrypt_chromium_value(blob_v20, key, db_version=20), 'my_secret_token')

        # Modern db_version >= 24 (32-byte host digest prefix)
        host_digest = b'A' * 32
        blob_v24 = _encrypt_chromium_cookie(host_digest + b'modern_token_123')
        self.assertEqual(decrypt_chromium_value(blob_v24, key, db_version=24), 'modern_token_123')

        # Chromium meta table version detection
        with sqlite3.connect(':memory:') as conn:
            conn.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)')
            conn.execute("INSERT INTO meta (key, value) VALUES ('version', '24')")
            self.assertEqual(_read_chromium_db_version(conn), 24)

    def test_gtk_ui_smoke(self):
        if not os.environ.get('DISPLAY'):
            self.skipTest('No DISPLAY available')
        from run import AppController
        from xattendo_widget import __version__
        from xattendo_widget.ui.styles import install_css

        install_css()
        for mode, expect_done in (('active', False), ('done', True)):
            ctrl = AppController(simulate=mode)
            try:
                pill = ctrl.pill
                self.assertIsNotNone(pill)
                self.assertEqual(pill.popup_win.version_lbl.get_text(), f'v{__version__}')
                self.assertEqual(pill.name_lbl.get_visible(), expect_done)
                self.assertEqual(pill.ring_widget._state, 'done' if expect_done else 'active')
                pill.popup_win.toggle_near(pill, pill.local_snapshot, pill.linked_state)
                self.assertTrue(pill.popup_win.get_visible())
                pill.popup_win._switch_page('sessions')
                self.assertEqual(pill.popup_win.stack.get_visible_child_name(), 'sessions')
                pill.popup_win._switch_page('overview')
                self.assertEqual(pill.popup_win.stack.get_visible_child_name(), 'overview')
                pill.popup_win.hide()
                if mode == 'active':
                    pill.history_win.open_window(pill.local_snapshot, pill.linked_state)
                    self.assertTrue(pill.history_win.get_visible())
                    pill.history_win.hide()
                    pill.settings_win.open_window(pill.linked_state)
                    self.assertTrue(pill.settings_win.get_visible())
                    pill.settings_win.close_window()
            finally:
                if ctrl.pill is not None:
                    ctrl.pill.cleanup()

    def test_session_tracker_locks_and_windows(self):
        merged = merge_session_intervals(
            [[1000.0, 1200.0]],
            [[900.0, 950.0], [1000.5, 1300.0], [1500.0, None]],
            session_start=980.0,
            now_ts=1600.0,
        )
        self.assertEqual(merged, [[1000.0, 1300.0], [1500.0, None]])

        locked_sec, lock_cnt, _ = normalize_and_sum_locks(merged, 980.0, 1600.0, 1600.0)
        self.assertEqual(lock_cnt, 2)
        self.assertAlmostEqual(locked_sec, 400.0, places=2)

        sessions = {
            'host|c1|1000': {
                'host': 'c3r3p4.1337.ma',
                'session_id': 'c1',
                'start_ts': 1000.0,
                'end_ts': None,
                'last_seen': 2000.0,
                'closed': False,
                'locked': False,
                'intervals': [[1200.0, 1300.0], [1500.0, 1700.0]],
            }
        }
        st = compute_session_stats(sessions['host|c1|1000'], True, 2000.0)
        self.assertTrue(st.live)
        self.assertFalse(st.locked_now)
        self.assertAlmostEqual(st.gross_sec, 1000.0, places=2)
        self.assertAlmostEqual(st.locked_sec, 300.0, places=2)
        self.assertAlmostEqual(st.net_sec, 700.0, places=2)

        wt = compute_window_totals(sessions, 'host|c1|1000', 0.0, 2000.0, 2000.0)
        self.assertEqual(wt.sessions, 1)
        self.assertAlmostEqual(wt.net_seconds, 700.0, places=2)

    def test_session_tracker_merges_live_estimate_readonly(self):
        now_ts = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            le_path = tmp_path / 'le_sessions.json'
            le_payload = {
                'version': 1,
                'sessions': {
                    'c3r3p4|c21|100': {
                        'host': 'c3r3p4.1337.ma',
                        'session_id': 'c21',
                        'start_ts': now_ts - 3600.0,
                        'end_ts': now_ts - 1800.0,
                        'last_seen': now_ts - 1800.0,
                        'closed': True,
                        'locked': False,
                        'intervals': [[now_ts - 3000.0, now_ts - 2400.0]],
                    }
                },
            }
            le_path.write_text(json.dumps(le_payload), encoding='utf-8')
            tracker = SessionTracker(
                ledger_path=tmp_path / 'x_sessions.json',
                lock_path=tmp_path / 'x_sessions.lock',
                live_estimate_path=le_path,
                seat0_path=tmp_path / 'missing_seat0.json',
            )
            snap = tracker.poll(now_ts=now_ts)
            self.assertGreaterEqual(snap.period.net_seconds, 1200.0)
            self.assertTrue(any(s.session_id == 'c21' and not s.live for s in snap.recent_sessions))
            # live_estimate ledger untouched
            self.assertEqual(json.loads(le_path.read_text(encoding='utf-8')), le_payload)

    def test_attendo_and_intra_parsers_and_fusion(self):
        rsc_payload = json.dumps([
            1,
            (
                '{"login":"ael-biss","todayHoursEstimation":"03:36","todayHours":null,'
                '"periods":['
                '{"weekStart":"2026-11-19","weekEnd":"2026-11-25","total":15.0,'
                '"daily":[{"date":"2026-11-19","hours":7.0,"counted":true},'
                '{"date":"2026-11-20","hours":8.0,"counted":true}]}'
                ']}'
            ),
        ])
        html = (
            '<html><body>'
            '<p>Attendance target 30h per counted-day period</p>'
            f'<script>self.__next_f.push({rsc_payload})</script>'
            '</body></html>'
        )
        parsed = parse_attendo_profile_html(html)
        self.assertEqual(parsed.login, 'ael-biss')
        self.assertEqual(parsed.target_hours, 30.0)
        self.assertEqual(parsed.current.total, 15.0)
        self.assertEqual(parsed.current.counted_days, 2)

        intra = parse_intra_locations_json({'2026-11-22': '04:30:38'})
        self.assertEqual(intra['2026-11-22'], 4 * 3600 + 30 * 60 + 38)

        _local, linked = build_simulated_local_and_linked('active')
        p_net, target_h, _s, _e, pct, left_h = merge_period_progress(
            3 * 3600,
            3 * 3600 + 36 * 60,
            linked,
            fallback_target_hours=30.0,
            today_iso=campus_today().isoformat(),
        )
        self.assertEqual(target_h, 30.0)
        self.assertAlmostEqual(p_net / 3600.0, 21.6, places=2)
        self.assertAlmostEqual(pct, 72.0, places=1)
        self.assertAlmostEqual(left_h, 8.4, places=1)

    def test_compute_effective_today_metrics(self):
        local, linked = build_simulated_local_and_linked('active')
        # Simulate morning hours: Intra has 7.28h gross, local tracker only saw 4.51h gross, 1.03h locked
        linked.intra_today_seconds = 7.28 * 3600.0
        local.today = type(local.today)(
            net_seconds=3.48 * 3600.0,
            locked_seconds=1.03 * 3600.0,
            gross_seconds=4.51 * 3600.0,
            sessions=1,
        )
        net, gross, locked = compute_effective_today_metrics(local, linked, now_ts=linked.fetched_at)
        self.assertAlmostEqual(gross / 3600.0, 7.28, places=2)
        self.assertAlmostEqual(locked / 3600.0, 1.03, places=2)
        self.assertAlmostEqual(net / 3600.0, 6.25, places=2)

        # Active ticking (+30s advances net & gross by 30s)
        net2, gross2, locked2 = compute_effective_today_metrics(local, linked, now_ts=linked.fetched_at + 30.0)
        self.assertAlmostEqual(net2 - net, 30.0, places=2)
        self.assertAlmostEqual(gross2 - gross, 30.0, places=2)
        self.assertAlmostEqual(locked2, locked, places=2)

        # Locked ticking (+30s to both gross and locked -> net stays paused)
        local.today = type(local.today)(
            net_seconds=3.48 * 3600.0,
            locked_seconds=1.03 * 3600.0 + 30.0,
            gross_seconds=4.51 * 3600.0 + 30.0,
            sessions=1,
        )
        net3, _g3, locked3 = compute_effective_today_metrics(local, linked, now_ts=linked.fetched_at + 30.0)
        self.assertAlmostEqual(net3, net, places=2)
        self.assertAlmostEqual(locked3 - locked, 30.0, places=2)

        # Attendo-only fallback when Intra is unlinked
        linked.intra_linked = False
        linked.intra_today_seconds = None
        linked.attendo_recorded_today_seconds = 6 * 3600.0
        linked.attendo_live_seconds = None
        net_att, gross_att, _l_att = compute_effective_today_metrics(local, linked, now_ts=linked.fetched_at)
        self.assertEqual(net_att, 6 * 3600.0)
        self.assertGreaterEqual(gross_att, net_att + locked3)

        # Unlinked fallback uses local tracker directly
        net_u, gross_u, locked_u = compute_effective_today_metrics(local, None)
        self.assertEqual(net_u, local.today.net_seconds)
        self.assertEqual(gross_u, local.today.gross_seconds)
        self.assertEqual(locked_u, local.today.locked_seconds)

    def test_session_tracker_merges_sqlite_day_locks_without_double_count(self):
        now_ts = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shared_db = tmp_path / 'locks.sqlite3'
            with sqlite3.connect(shared_db) as db:
                db.execute('CREATE TABLE intervals (username TEXT, start REAL, end REAL, is_open INTEGER)')
                # Morning lock: 600s, plus overlapping lock that should merge cleanly
                db.execute('INSERT INTO intervals VALUES (?, ?, ?, 0)', ('ael-biss', now_ts - 1800, now_ts - 1200))
                db.execute('INSERT INTO intervals VALUES (?, ?, ?, 0)', ('ael-biss', now_ts - 1500, now_ts - 1100))

            snap = SessionTracker._build_snapshot(
                sessions={},
                baselines={},
                current_key=None,
                now_ts=now_ts,
                username='ael-biss',
                shared_db=shared_db,
                legacy_db=tmp_path / 'missing_legacy.sqlite3',
            )
            self.assertEqual(len(snap.today_locks), 1)
            self.assertAlmostEqual(snap.today.locked_seconds, 700.0, places=1)

    def test_calculate_daily_average_target(self):
        # 24h prior across 4/7 days, 30h target -> 6h / 3d = 2.0h daily target
        local, linked = build_simulated_local_and_linked('done')
        day_after_4 = (datetime.date.fromisoformat(linked.current_period.start) + datetime.timedelta(days=4)).isoformat()

        d_half = calculate_daily_average_target(local, linked, 1.0 * 3600.0, today_iso=day_after_4)
        self.assertAlmostEqual(d_half.remaining_period_hours, 6.0, places=2)
        self.assertEqual(d_half.remaining_days, 3)
        self.assertAlmostEqual(d_half.daily_target_seconds, 2.0 * 3600.0, places=1)
        self.assertAlmostEqual(d_half.remaining_today_seconds, 1.0 * 3600.0, places=1)
        self.assertAlmostEqual(d_half.fraction, 0.5, places=2)
        self.assertFalse(d_half.done)

        d_done = calculate_daily_average_target(local, linked, 2.0 * 3600.0, today_iso=day_after_4)
        self.assertEqual(d_done.remaining_today_seconds, 0.0)
        self.assertEqual(d_done.fraction, 1.0)
        self.assertTrue(d_done.done)

        # 18h prior across 3/7 days, 30h target -> 12h / 4d = 3.0h daily target
        local_a, linked_a = build_simulated_local_and_linked('active')
        today_iso = campus_today().isoformat()
        d_act = calculate_daily_average_target(local_a, linked_a, 2.1 * 3600.0, today_iso=today_iso)
        self.assertAlmostEqual(d_act.remaining_period_hours, 12.0, places=2)
        self.assertEqual(d_act.remaining_days, 4)
        self.assertAlmostEqual(d_act.daily_target_seconds, 3.0 * 3600.0, places=1)
        self.assertAlmostEqual(d_act.fraction, 0.7, places=2)
        self.assertFalse(d_act.done)

        # Period already complete (24h prior) -> done=True immediately
        linked.target_hours = 24.0
        d_full = calculate_daily_average_target(local, linked, 0.0, today_iso=day_after_4)
        self.assertEqual(d_full.daily_target_seconds, 0.0)
        self.assertEqual(d_full.fraction, 1.0)
        self.assertTrue(d_full.done)

        # Unlinked fallback
        local_u, _ = build_simulated_local_and_linked('unlinked')
        d_unlinked = calculate_daily_average_target(local_u, None, 2.0 * 3600.0, fallback_target_hours=30.0)
        self.assertGreater(d_unlinked.daily_target_seconds, 0.0)
        self.assertFalse(d_unlinked.done)

    def test_eta_and_day_active_segments(self):
        # 14:00 + 2h 49m = 16:49
        now_dt = datetime.datetime(2026, 11, 22, 14, 0, 0, tzinfo=datetime.timezone.utc)
        eta = format_eta_clock(now_dt.timestamp(), 2 * 3600 + 49 * 60)
        self.assertEqual(eta, '16:49')

        local, _ = build_simulated_local_and_linked('active', now_ts=now_dt.timestamp())
        w_start, w_end, segs, ts = build_day_active_segments(local, now_ts=now_dt.timestamp())
        self.assertLess(w_start, w_end)
        self.assertEqual(ts, now_dt.timestamp())
        # Session has a lock interval in the middle, so it splits into 2 active blocks
        self.assertEqual(len(segs), 2)
        total_active = sum(b - a for a, b in segs)
        self.assertAlmostEqual(total_active, local.current_session.net_sec, places=1)

    def test_attendo_period_bounds_thu_wed(self):
        # Sunday 2026-11-22 -> Thu 2026-11-19 to Wed 2026-11-25
        dt = datetime.datetime(2026, 11, 22, 18, 0, 0)
        start_d, end_d = attendo_period_bounds(dt)
        self.assertEqual(start_d.isoformat(), '2026-11-19')
        self.assertEqual(end_d.isoformat(), '2026-11-25')

    def test_goal_rounding_and_clip(self):
        p = calculate_goal_progress(6 * 3600 + 35 * 60, 7 * 3600)
        self.assertTrue(p.reached)
        self.assertEqual(calculate_expected_recorded_hours(5 * 3600 + 35 * 60), 6)
        self.assertEqual(clip_and_merge_intervals([(90, 150), (140, 220)], 100, 200), [(100, 200)])

    def test_config_roundtrip_and_clamping(self):
        cfg = UserConfig(
            refresh_interval_seconds=90,
            pill_display_mode='hours',
            browser_preference='brave',
            period_target_hours=42.0,
            intra_login='ael-biss',
            attendo_token='tok_xyz',
            language='fr',
        )
        restored = UserConfig.from_dict(cfg.to_dict())
        self.assertEqual(restored.refresh_interval_seconds, 90)
        self.assertEqual(restored.pill_display_mode, 'hours')
        self.assertEqual(restored.browser_preference, 'brave')
        self.assertEqual(restored.period_target_hours, 42.0)
        self.assertEqual(restored.intra_login, 'ael-biss')
        self.assertEqual(restored.attendo_token, 'tok_xyz')
        self.assertEqual(restored.language, 'fr')

        clamped = UserConfig.from_dict({
            'refreshIntervalSeconds': 5,
            'periodTargetHours': 999,
            'pillDisplayMode': 'invalid',
            'browserPreference': 'safari',
            'language': 'xx',
        })
        self.assertEqual(clamped.refresh_interval_seconds, 30)
        self.assertEqual(clamped.period_target_hours, 200.0)
        self.assertEqual(clamped.pill_display_mode, 'hms')
        self.assertEqual(clamped.browser_preference, 'auto')
        self.assertEqual(clamped.language, 'en')

    def test_i18n_parity_and_rtl(self):
        en_keys = set(STRINGS['en'].keys())
        self.assertEqual(en_keys, set(STRINGS['fr'].keys()))
        self.assertEqual(en_keys, set(STRINGS['ar'].keys()))
        self.assertFalse(is_rtl('en'))
        self.assertTrue(is_rtl('ar'))
        self.assertEqual(normalize_lang('FR'), 'fr')
        self.assertEqual(tr('en', 'logtime_title'), 'Logtime')
        self.assertTrue(len(format_date(campus_today(), 'ar')) > 0)

    def test_x11_topbar_structs_and_masks(self):
        buf = (ctypes.c_ubyte * 4)()
        set_xi_mask(buf, XI_RAW_BUTTON_PRESS)
        set_xi_mask(buf, XI_RAW_BUTTON_RELEASE)
        set_xi_mask(buf, XI_RAW_MOTION)
        self.assertTrue(buf[XI_RAW_BUTTON_PRESS >> 3] & (1 << (XI_RAW_BUTTON_PRESS & 7)))
        self.assertGreaterEqual(ctypes.sizeof(XEvent), 24 * ctypes.sizeof(ctypes.c_long))
        self.assertGreater(ctypes.sizeof(XGenericEventCookie), 0)
        self.assertGreater(ctypes.sizeof(XIRawEvent), 0)

    def test_update_semver_and_simulations(self):
        self.assertEqual(parse_semver('v1.2.3'), (1, 2, 3))
        self.assertTrue(is_newer_version('v1.0.1', '1.0.0'))
        for mode in ('active', 'locked', 'done', 'unlinked'):
            local, linked = build_simulated_local_and_linked(mode)
            self.assertIsNotNone(local.current_session)
            if mode == 'locked':
                self.assertTrue(local.current_session.locked_now)
            if mode == 'unlinked':
                self.assertFalse(linked.attendo_linked)
                self.assertFalse(linked.intra_linked)


if __name__ == '__main__':
    unittest.main()
