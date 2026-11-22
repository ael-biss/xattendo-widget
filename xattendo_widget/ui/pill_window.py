"""Always-on-top draggable desktop pill widget and GNOME Top Bar overlay controller."""

import datetime
import math
import os
import sys
import time
from typing import Callable, Optional, Set, Tuple

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib, Gtk

from xattendo_widget.constants import APP_NAME
from xattendo_widget.core.calculator import (
    build_simulated_local_and_linked,
    calculate_daily_average_target,
    campus_today,
    compute_effective_today_metrics,
    format_dec_hours,
    format_hms,
    merge_period_progress,
)
from xattendo_widget.i18n import is_rtl, tr
from xattendo_widget.models import DailyTargetProgress, LinkedAccountsState, LocalTrackerSnapshot, UserConfig
from xattendo_widget.services.account_linker import AccountLinker
from xattendo_widget.services.config_service import ConfigService
from xattendo_widget.services.session_tracker import SessionTracker
from xattendo_widget.services.system_service import SystemService
from xattendo_widget.services.update_service import UpdateService
from xattendo_widget.services.x11_topbar import (
    BUTTON1_MASK,
    BUTTON2_MASK,
    X11TopBarInputMonitor,
    is_x11_session,
)
from xattendo_widget.ui.history_window import HistoryWindow
from xattendo_widget.ui.popup_window import PopupWindow
from xattendo_widget.ui.ring_widget import ProgressRing
from xattendo_widget.ui.settings_window import SettingsWindow
from xattendo_widget.ui.styles import apply_rtl_layout, enable_rgba


class PillWindow(Gtk.Window):
    def __init__(
        self,
        config_service: ConfigService,
        session_tracker: SessionTracker,
        account_linker: AccountLinker,
        system_service: SystemService,
        update_service: Optional[UpdateService] = None,
        simulate: Optional[str] = None,
        on_top_bar_mode_changed: Optional[Callable[[bool], None]] = None,
        initial_linked: Optional[LinkedAccountsState] = None,
        initial_triggered_events: Optional[Set[str]] = None,
        check_updates: bool = True,
    ) -> None:
        self._top_bar_mode = bool(config_service.config.top_bar_mode) and is_x11_session()
        win_type = Gtk.WindowType.POPUP if self._top_bar_mode else Gtk.WindowType.TOPLEVEL
        super().__init__(type=win_type)

        self.config_service = config_service
        self.session_tracker = session_tracker
        self.account_linker = account_linker
        self.system_service = system_service
        self.update_service = update_service or UpdateService()
        self.simulate = simulate
        self.on_top_bar_mode_changed = on_top_bar_mode_changed

        self._tick_source_id: Optional[int] = None
        self._sync_source_id: Optional[int] = None
        self._x11_monitor: Optional[X11TopBarInputMonitor] = None
        self._hidden_by_env = False
        self._syncing = False

        self.local_snapshot: Optional[LocalTrackerSnapshot] = None
        self.linked_state: Optional[LinkedAccountsState] = initial_linked
        self.triggered_events: Set[str] = set(initial_triggered_events) if initial_triggered_events else set()
        self._last_poll_mono: float = 0.0
        self._last_campus_day: datetime.date = campus_today()

        self._pos_x: int = 0
        self._pos_y: int = 0

        # Floating-mode GTK drag state
        self._dragging = False
        self._drag_moved = False
        self._drag_start_x = 0.0
        self._drag_start_y = 0.0
        self._win_start_x = 0
        self._win_start_y = 0

        # Top-bar XInput2 raw interaction state
        self._raw_dragging = False
        self._raw_drag_button = 0
        self._raw_drag_moved = False
        self._raw_drag_start_x = 0
        self._raw_drag_start_y = 0
        self._raw_win_start_x = 0
        self._raw_hovered = False

        self.get_style_context().add_class('xattendo-transparent')
        self.set_title(APP_NAME)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_resizable(False)
        self.stick()
        enable_rgba(self)

        event_box = Gtk.EventBox()
        event_box.set_visible_window(False)
        if not self._top_bar_mode:
            event_box.add_events(
                Gdk.EventMask.BUTTON_PRESS_MASK
                | Gdk.EventMask.BUTTON_RELEASE_MASK
                | Gdk.EventMask.POINTER_MOTION_MASK
            )
            event_box.connect('button-press-event', self._on_button_press)
            event_box.connect('button-release-event', self._on_button_release)
            event_box.connect('motion-notify-event', self._on_motion)

        spacing = 6 if self._top_bar_mode else 8
        self.pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
        self.pill.get_style_context().add_class('xattendo-pill')
        if self._top_bar_mode:
            self.pill.get_style_context().add_class('top-bar-mode')
        event_box.add(self.pill)
        self.add(event_box)

        ring_size = 16 if self._top_bar_mode else 18
        self.ring_widget = ProgressRing(size=ring_size)
        self.ring_widget.set_valign(Gtk.Align.CENTER)
        self.pill.pack_start(self.ring_widget, False, False, 0)

        self.name_lbl = Gtk.Label(label=tr(self.config_service.config.language, 'pill_done'))
        self.name_lbl.get_style_context().add_class('xattendo-pill-name')
        self.name_lbl.set_no_show_all(True)
        self.pill.pack_start(self.name_lbl, False, False, 0)

        self.sep_lbl = Gtk.Label(label='|')
        self.sep_lbl.get_style_context().add_class('xattendo-pill-sep')
        self.sep_lbl.set_no_show_all(True)
        self.pill.pack_start(self.sep_lbl, False, False, 0)

        self.time_lbl = Gtk.Label(label='00:00:00')
        self.time_lbl.set_direction(Gtk.TextDirection.LTR)
        self.time_lbl.get_style_context().add_class('xattendo-pill-time')
        self.pill.pack_start(self.time_lbl, False, False, 0)

        self.settings_win = SettingsWindow(
            config_service=self.config_service,
            update_service=self.update_service,
            on_reset_position=self.reset_position,
            on_sync_accounts=self.sync_accounts,
            on_open_url=self.system_service.open_url,
            on_top_bar_mode_changed=self._handle_top_bar_mode_changed,
            on_top_bar_preset=self.apply_top_bar_preset,
            on_reload_app=self.reload_app,
            on_quit_app=self.quit_app,
        )
        self.history_win = HistoryWindow(
            config_service=self.config_service,
            on_refresh=self.sync_accounts,
        )
        self.popup_win = PopupWindow(
            config_service=self.config_service,
            on_open_settings=lambda: self.settings_win.open_window(self.linked_state),
            on_open_history=lambda: self.history_win.open_window(self._current_local_for_ui(), self.linked_state),
            on_open_url=self.system_service.open_url,
            on_refresh=self.sync_accounts,
            on_reload=self.reload_app,
            on_quit=self.quit_app,
        )

        self.connect('size-allocate', self._on_size_allocate)
        self.config_service.subscribe(self._on_config_changed)

        if self._top_bar_mode:
            self._x11_monitor = X11TopBarInputMonitor(
                on_button_press=self._on_raw_button_press,
                on_button_release=self._on_raw_button_release,
                on_motion=self._on_raw_motion,
                on_screensaver_changed=self._on_screensaver_changed,
            )
            if not self._x11_monitor.start():
                self._x11_monitor = None
                self.config_service.config.top_bar_mode = False
                self.config_service.save(notify=False)
                if self.on_top_bar_mode_changed:
                    GLib.idle_add(self.on_top_bar_mode_changed, False)

        self.show_all()
        apply_rtl_layout(self, is_rtl(self.config_service.config.language), ltr_widgets=(self.time_lbl,))
        GLib.idle_add(self._apply_initial_position)

        if self.simulate:
            self.local_snapshot, self.linked_state = build_simulated_local_and_linked(self.simulate)
        else:
            self.local_snapshot = self.session_tracker.poll(closing=False)
            self._last_poll_mono = time.monotonic()
            if self.linked_state is None:
                self.sync_accounts()

        self._on_tick()
        self._tick_source_id = GLib.timeout_add_seconds(1, self._on_tick)
        self._schedule_account_sync()

        if check_updates and self.update_service.is_configured and not self.simulate:
            self.update_service.check_async(self._on_startup_update_check)

    def cleanup(self) -> None:
        if self._tick_source_id is not None:
            GLib.source_remove(self._tick_source_id)
            self._tick_source_id = None
        if self._sync_source_id is not None:
            GLib.source_remove(self._sync_source_id)
            self._sync_source_id = None
        if self._x11_monitor is not None:
            self._x11_monitor.stop()
            self._x11_monitor = None
        if not self.simulate:
            try:
                self.session_tracker.poll(closing=False)
            except Exception:
                pass
        self.config_service.unsubscribe(self._on_config_changed)
        self.popup_win.destroy()
        self.history_win.destroy()
        self.settings_win.destroy()
        self.destroy()

    def _schedule_account_sync(self) -> None:
        if self._sync_source_id is not None:
            GLib.source_remove(self._sync_source_id)
            self._sync_source_id = None
        if not self.simulate:
            interval = max(30, self.config_service.config.refresh_interval_seconds)
            self._sync_source_id = GLib.timeout_add_seconds(interval, self._on_sync_timer)

    def _on_sync_timer(self) -> bool:
        self.sync_accounts()
        return True

    def sync_accounts(self) -> None:
        if self.simulate or self._syncing:
            return
        self._syncing = True
        cfg = self.config_service.config

        def on_done(state: LinkedAccountsState) -> None:
            GLib.idle_add(self._on_accounts_synced, state)

        self.account_linker.sync_async(
            browser_pref=cfg.browser_preference,
            intra_login=cfg.intra_login,
            attendo_token=cfg.attendo_token,
            intra_cookie=cfg.intra_cookie,
            on_result=on_done,
        )

    def _on_accounts_synced(self, state: LinkedAccountsState) -> bool:
        self._syncing = False
        self.linked_state = state
        self.settings_win.update_linked_status(state)
        self._on_tick()
        return False

    def _handle_top_bar_mode_changed(self, enabled: bool) -> bool:
        if self.on_top_bar_mode_changed:
            self.on_top_bar_mode_changed(enabled)
        return False

    def reload_app(self) -> None:
        if self._x11_monitor is not None:
            self._x11_monitor.stop()
            self._x11_monitor = None
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def quit_app(self) -> None:
        Gtk.main_quit()

    def _on_startup_update_check(
        self,
        remote_version: Optional[str],
        _download_url: Optional[str],
        _error: Optional[str],
    ) -> None:
        if remote_version:
            lang = self.config_service.config.language
            GLib.idle_add(
                self.system_service.notify,
                tr(lang, 'notif_update_title'),
                tr(lang, 'notif_update_body', version=remote_version),
                self.config_service.config.notifications_enabled,
            )

    def _on_config_changed(self, cfg: UserConfig) -> None:
        if cfg.position_locked:
            self._raw_dragging = False
            self._raw_drag_button = 0
            self._dragging = False
        apply_rtl_layout(self, is_rtl(cfg.language), ltr_widgets=(self.time_lbl,))
        self.popup_win.apply_language(cfg.language)
        self.history_win.apply_language(cfg.language)
        self._schedule_account_sync()
        self._on_tick()

    def _get_monitor_metrics(self) -> Tuple[Gdk.Rectangle, int]:
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geo = monitor.get_geometry()
        wa = monitor.get_workarea()
        raw_panel_h = wa.y - geo.y
        panel_h = raw_panel_h if 16 <= raw_panel_h <= 64 else 28
        return (geo, panel_h)

    def _top_bar_y(self) -> int:
        geo, panel_h = self._get_monitor_metrics()
        _, height = self.get_size()
        return geo.y + max(0, (panel_h - height) // 2)

    def _move_to(self, x: int, y: int) -> None:
        self._pos_x = x
        self._pos_y = y
        self.move(x, y)

    def get_screen_rect(self) -> Tuple[int, int, int, int]:
        width, height = self.get_size()
        if self._top_bar_mode:
            return (self._pos_x, self._pos_y, width, height)
        px, py = self.get_position()
        return (px, py, width, height)

    def _clamp_position(self, x: int, y: int) -> Tuple[int, int]:
        geo, panel_h = self._get_monitor_metrics()
        width, height = self.get_size()
        min_x = geo.x + 4
        max_x = geo.x + geo.width - max(width, 120) - 4
        if self._top_bar_mode:
            return (max(min_x, min(x, max_x)), self._top_bar_y())
        min_y = geo.y + panel_h
        max_y = geo.y + geo.height - max(height, 30) - 4
        return (max(min_x, min(x, max_x)), max(min_y, min(y, max_y)))

    def _on_size_allocate(self, _widget, _allocation) -> None:
        if not self._top_bar_mode or self._hidden_by_env:
            return
        nx, ny = self._clamp_position(self._pos_x, self._top_bar_y())
        if nx != self._pos_x or ny != self._pos_y:
            self._move_to(nx, ny)

    def _apply_initial_position(self) -> bool:
        cfg = self.config_service.config
        if self._top_bar_mode:
            if isinstance(cfg.top_bar_x, int):
                cx, cy = self._clamp_position(cfg.top_bar_x, self._top_bar_y())
                self._move_to(cx, cy)
                if cx != cfg.top_bar_x:
                    cfg.top_bar_x = cx
                    self.config_service.save(notify=False)
            else:
                self.reset_position()
            self._update_env_visibility()
            return False

        if isinstance(cfg.widget_x, int) and isinstance(cfg.widget_y, int):
            cx, cy = self._clamp_position(cfg.widget_x, cfg.widget_y)
            self._move_to(cx, cy)
            if cx != cfg.widget_x or cy != cfg.widget_y:
                cfg.widget_x, cfg.widget_y = cx, cy
                self.config_service.save(notify=False)
        else:
            self.reset_position()
        return False

    def apply_top_bar_preset(self, preset: str) -> None:
        geo, _ = self._get_monitor_metrics()
        if preset == 'left':
            target_x = geo.x + int(geo.width * 0.28)
        elif preset == 'center_right':
            target_x = geo.x + int(geo.width * 0.62)
        else:
            target_x = geo.x + int(geo.width * 0.74)

        if self._top_bar_mode:
            nx, ny = self._clamp_position(target_x, self._top_bar_y())
            self._move_to(nx, ny)
            self.config_service.config.top_bar_x = nx
        else:
            self.config_service.config.top_bar_x = target_x
        self.config_service.save(notify=False)

    def reset_position(self) -> None:
        if self._top_bar_mode:
            self.apply_top_bar_preset('right')
            return
        geo, panel_h = self._get_monitor_metrics()
        x = geo.x + geo.width - 190
        y = geo.y + panel_h + 4
        x, y = self._clamp_position(x, y)
        self._move_to(x, y)
        self.config_service.config.widget_x = x
        self.config_service.config.widget_y = y
        self.config_service.save(notify=False)

    # --- Top Bar Mode XInput2 Raw Pointer Handlers ---

    def _x11_to_logical(self, rx_px: int, ry_px: int) -> Tuple[int, int]:
        scale = max(1, self.get_scale_factor())
        return (rx_px // scale, ry_px // scale)

    def _hit_test_top_bar(self, lx: int, ly: int) -> bool:
        if self._hidden_by_env or not self.get_visible():
            return False
        geo, panel_h = self._get_monitor_metrics()
        px, py, pw, ph = self.get_screen_rect()
        top_edge = min(py, geo.y)
        bottom_edge = max(py + ph, geo.y + panel_h)
        return (px <= lx <= px + pw) and (top_edge <= ly <= bottom_edge)

    def _set_raw_hover(self, hovered: bool) -> None:
        if hovered == self._raw_hovered:
            return
        self._raw_hovered = hovered
        ctx = self.pill.get_style_context()
        if hovered:
            ctx.add_class('xattendo-pill-hover')
        else:
            ctx.remove_class('xattendo-pill-hover')

    def _on_raw_button_press(self, button: int, rx_px: int, ry_px: int) -> None:
        lx, ly = self._x11_to_logical(rx_px, ry_px)
        geo, panel_h = self._get_monitor_metrics()
        in_top_bar = geo.y <= ly <= geo.y + panel_h
        if in_top_bar and self.settings_win.get_visible() and not self.settings_win.is_modal_open:
            self.settings_win.close_window()
            return
        if in_top_bar and self.popup_win.get_visible() and not self._hit_test_top_bar(lx, ly):
            self.popup_win.hide()
            return
        if not self._hit_test_top_bar(lx, ly):
            return
        if button == 2 and self.config_service.config.position_locked:
            return
        if button in (1, 2):
            self._raw_dragging = True
            self._raw_drag_button = button
            self._raw_drag_moved = False
            self._raw_drag_start_x = lx
            self._raw_drag_start_y = ly
            self._raw_win_start_x = self._pos_x
        elif button == 3:
            self.popup_win.hide()
            self.history_win.hide()
            self.settings_win.open_window(self.linked_state)

    def _finish_raw_drag(self, button: int) -> None:
        was_moved = self._raw_drag_moved
        self._raw_dragging = False
        self._raw_drag_button = 0
        self._raw_drag_moved = False
        if was_moved:
            self.config_service.config.top_bar_x = self._pos_x
            self.config_service.save(notify=False)
        elif button == 1:
            self.popup_win.toggle_near(self, self._current_local_for_ui(), self.linked_state)

    def _on_raw_motion(self, rx_px: int, ry_px: int, mask: int) -> None:
        lx, ly = self._x11_to_logical(rx_px, ry_px)
        self._set_raw_hover(self._hit_test_top_bar(lx, ly))
        if not self._raw_dragging:
            return
        expected_mask = BUTTON1_MASK if self._raw_drag_button == 1 else BUTTON2_MASK
        if (mask & expected_mask) == 0:
            self._finish_raw_drag(self._raw_drag_button)
            return
        if self.config_service.config.position_locked:
            return
        dx = lx - self._raw_drag_start_x
        if abs(dx) > 6:
            self._raw_drag_moved = True
            if self.popup_win.get_visible():
                self.popup_win.hide()
            nx, ny = self._clamp_position(self._raw_win_start_x + dx, self._top_bar_y())
            self._move_to(nx, ny)

    def _on_raw_button_release(self, button: int, _rx_px: int, _ry_px: int) -> None:
        if not self._raw_dragging or button != self._raw_drag_button:
            return
        self._finish_raw_drag(button)

    def _on_screensaver_changed(self, _active: bool) -> None:
        GLib.idle_add(self._update_env_visibility)

    def _update_env_visibility(self) -> bool:
        if not self._top_bar_mode or not self._x11_monitor:
            return False
        should_hide = (
            self._x11_monitor.screensaver_active
            or self._x11_monitor.is_fullscreen_active()
        )
        if should_hide and not self._hidden_by_env:
            self._hidden_by_env = True
            self._raw_dragging = False
            self._set_raw_hover(False)
            self.popup_win.hide()
            self.hide()
        elif not should_hide and self._hidden_by_env:
            self._hidden_by_env = False
            self.show_all()
            nx, ny = self._clamp_position(self._pos_x, self._top_bar_y())
            self._move_to(nx, ny)
        return False

    # --- Floating Mode GTK Pointer Handlers ---

    def _on_button_press(self, _widget, event) -> bool:
        if self.settings_win.get_visible() and not self.settings_win.is_modal_open:
            self.settings_win.close_window()
            return True
        if event.button == 1:
            self._dragging = True
            self._drag_moved = False
            self._drag_start_x = event.x_root
            self._drag_start_y = event.y_root
            self._win_start_x, self._win_start_y = self.get_position()
            return True
        if event.button == 3:
            self.popup_win.hide()
            self.history_win.hide()
            self.settings_win.open_window(self.linked_state)
            return True
        return False

    def _on_motion(self, _widget, event) -> bool:
        if not self._dragging or self.config_service.config.position_locked:
            return False
        dx = int(event.x_root - self._drag_start_x)
        dy = int(event.y_root - self._drag_start_y)
        if abs(dx) > 4 or abs(dy) > 4:
            self._drag_moved = True
            if self.popup_win.get_visible():
                self.popup_win.hide()
            nx, ny = self._clamp_position(self._win_start_x + dx, self._win_start_y + dy)
            self._move_to(nx, ny)
        return True

    def _on_button_release(self, _widget, event) -> bool:
        if event.button == 1 and self._dragging:
            self._dragging = False
            if self._drag_moved:
                x, y = self.get_position()
                self._pos_x, self._pos_y = x, y
                self.config_service.config.widget_x = x
                self.config_service.config.widget_y = y
                self.config_service.save(notify=False)
            else:
                self.popup_win.toggle_near(self, self._current_local_for_ui(), self.linked_state)
            return True
        return False

    # --- Live 1-Second Interpolation & Tick ---

    def _current_local_for_ui(self) -> Optional[LocalTrackerSnapshot]:
        base = self.local_snapshot
        if base is None:
            return None
        cur = base.current_session
        if cur is None or not cur.live:
            return base

        elapsed = max(0.0, time.time() - base.now_ts)
        if elapsed < 0.25:
            return base

        add_net = 0.0 if cur.locked_now else elapsed
        add_lock = elapsed if cur.locked_now else 0.0
        new_cur = type(cur)(
            host=cur.host,
            session_id=cur.session_id,
            start_ts=cur.start_ts,
            end_ts=cur.end_ts + elapsed,
            live=cur.live,
            locked_now=cur.locked_now,
            gross_sec=cur.gross_sec + elapsed,
            locked_sec=cur.locked_sec + add_lock,
            net_sec=cur.net_sec + add_net,
            lock_count=cur.lock_count,
            intervals=cur.intervals,
        )

        def _bump(wt):
            return type(wt)(
                net_seconds=wt.net_seconds + add_net,
                locked_seconds=wt.locked_seconds + add_lock,
                gross_seconds=wt.gross_seconds + elapsed,
                sessions=wt.sessions,
            )

        return LocalTrackerSnapshot(
            now_ts=base.now_ts + elapsed,
            current_session=new_cur,
            today=_bump(base.today),
            period_start=base.period_start,
            period_end=base.period_end,
            period=_bump(base.period),
            week=_bump(base.week),
            month=_bump(base.month),
            today_locks=base.today_locks,
            recent_sessions=base.recent_sessions,
        )

    def _check_notifications(
        self,
        daily: DailyTargetProgress,
        today_net: float,
        p_net: float,
        target_h: float,
        p_start: str,
    ) -> None:
        cfg = self.config_service.config
        lang = cfg.language
        today_iso = campus_today().isoformat()

        if daily.daily_target_seconds > 0:
            daily_target_str = format_dec_hours(daily.daily_target_seconds)
            if daily.done and cfg.goal_reached_notify:
                key = f'{today_iso}-daily-done'
                if key not in self.triggered_events:
                    self.triggered_events.add(key)
                    self.system_service.notify(
                        tr(lang, 'notif_daily_done_title'),
                        tr(lang, 'notif_daily_done_body', target=daily_target_str, logged=format_dec_hours(today_net)),
                        enabled=cfg.notifications_enabled,
                    )
            elif not daily.done and cfg.almost_goal_enabled:
                rem_daily_min = math.ceil(daily.remaining_today_seconds / 60.0)
                if 0 < rem_daily_min <= cfg.almost_goal_minutes:
                    key = f'{today_iso}-daily-almost'
                    if key not in self.triggered_events:
                        self.triggered_events.add(key)
                        self.system_service.notify(
                            tr(lang, 'notif_daily_almost_title'),
                            tr(lang, 'notif_daily_almost_body', minutes=rem_daily_min, target=daily_target_str),
                            enabled=cfg.notifications_enabled,
                        )

        rem_min = math.ceil(max(0.0, target_h * 3600.0 - p_net) / 60.0)
        goal_str = f'{int(target_h)}h' if target_h == int(target_h) else f'{target_h:.1f}h'
        period_key = p_start or today_iso

        if rem_min == 0 and cfg.goal_reached_notify:
            key = f'{period_key}-goal-reached'
            if key not in self.triggered_events:
                self.triggered_events.add(key)
                self.system_service.notify(
                    tr(lang, 'notif_goal_title'),
                    tr(lang, 'notif_goal_body', goal=goal_str, logged=format_dec_hours(p_net)),
                    enabled=cfg.notifications_enabled,
                )

    def _on_tick(self) -> bool:
        if self._top_bar_mode:
            self._update_env_visibility()
            if self._raw_dragging and self._x11_monitor:
                ptr = self._x11_monitor.query_pointer()
                if ptr is not None:
                    expected_mask = BUTTON1_MASK if self._raw_drag_button == 1 else BUTTON2_MASK
                    if (ptr[2] & expected_mask) == 0:
                        self._finish_raw_drag(self._raw_drag_button)

        now_mono = time.monotonic()
        if not self.simulate and (now_mono - self._last_poll_mono) >= 2.0:
            self._last_poll_mono = now_mono
            try:
                self.local_snapshot = self.session_tracker.poll(closing=False)
            except Exception:
                pass

        today = campus_today()
        if today != self._last_campus_day:
            self._last_campus_day = today
            self.triggered_events.clear()
            self.sync_accounts()

        local = self._current_local_for_ui()
        if local is None:
            return True

        cfg = self.config_service.config
        lang = cfg.language
        today_net, _today_gross, _today_locked = compute_effective_today_metrics(local, self.linked_state)
        daily = calculate_daily_average_target(
            local,
            self.linked_state,
            today_net,
            fallback_target_hours=cfg.period_target_hours,
        )
        p_net, target_h, p_start, _p_end, pct, _left_h = merge_period_progress(
            local.period.net_seconds,
            today_net,
            self.linked_state,
            fallback_target_hours=cfg.period_target_hours,
            default_start=local.period_start,
            default_end=local.period_end,
        )

        ctx = self.pill.get_style_context()
        ctx.remove_class('goal-reached')
        ctx.remove_class('locked-mode')

        locked_now = bool(local.current_session and local.current_session.locked_now)

        if daily.done:
            ctx.add_class('goal-reached')
            self.ring_widget.set_state(1.0, 'done')
            self.name_lbl.set_text(tr(lang, 'pill_done'))
            self.name_lbl.show()
            self.sep_lbl.show()
        elif locked_now:
            ctx.add_class('locked-mode')
            self.ring_widget.set_state(daily.fraction, 'locked')
            self.name_lbl.set_text(tr(lang, 'pill_locked'))
            self.name_lbl.show()
            self.sep_lbl.show()
        else:
            self.ring_widget.set_state(daily.fraction, 'active')
            self.name_lbl.hide()
            self.sep_lbl.hide()

        if cfg.pill_display_mode == 'hours':
            self.time_lbl.set_text(format_dec_hours(today_net))
        elif cfg.pill_display_mode == 'period_pct':
            self.time_lbl.set_text(f'{pct:.0f}%')
        else:
            self.time_lbl.set_text(format_hms(today_net))

        self._check_notifications(daily, today_net, p_net, target_h, p_start)

        if self.popup_win.get_visible():
            self.popup_win.update_content(local, self.linked_state)
        if self.history_win.get_visible():
            self.history_win.update_data(local, self.linked_state)

        return True
