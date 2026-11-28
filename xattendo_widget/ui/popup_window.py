"""Minimalist 42 Logtime-style dark card popup with Overview | Sessions | Settings tabs."""

import datetime
import time
from typing import Callable, Optional

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib, Gtk

from xattendo_widget import __version__
from xattendo_widget.constants import ATTENDO_LOGIN_URL, ATTENDO_PROFILE_URL, INTRA_PROFILE_URL
from xattendo_widget.core.calculator import (
    build_day_active_segments,
    calculate_daily_average_target,
    compute_effective_today_metrics,
    format_compact_hours,
    format_eta_clock,
    format_hm,
    format_hms,
    merge_period_progress,
)
from xattendo_widget.i18n import is_rtl, tr
from xattendo_widget.models import LinkedAccountsState, LocalTrackerSnapshot
from xattendo_widget.services.config_service import ConfigService
from xattendo_widget.services.update_service import UpdateInfo, UpdateService
from xattendo_widget.ui.ring_widget import CountedDaysBar, DayTimeline, HeaderIcon
from xattendo_widget.ui.styles import apply_rtl_layout, enable_rgba


class PopupWindow(Gtk.Window):
    def __init__(
        self,
        config_service: ConfigService,
        on_open_settings: Callable[[], None],
        on_open_history: Callable[[], None],
        on_open_url: Callable[[str], None],
        on_refresh: Callable[[], None],
        on_reload: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
        on_open_web_login: Optional[Callable[[str], None]] = None,
        update_service: Optional[UpdateService] = None,
        on_restart_after_update: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.config_service = config_service
        self.on_open_settings = on_open_settings
        self.on_open_history = on_open_history
        self.on_open_url = on_open_url
        self.on_refresh = on_refresh
        self.on_reload = on_reload
        self.on_quit = on_quit
        self.on_open_web_login = on_open_web_login
        self.update_service = update_service
        self.on_restart_after_update = on_restart_after_update
        self._opened_at: float = 0.0
        self._active_page: str = 'overview'
        self._pending_update: Optional[UpdateInfo] = None
        self._updating: bool = False

        self.get_style_context().add_class('xattendo-transparent')
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_resizable(False)
        self.stick()
        enable_rgba(self)

        self.connect('key-press-event', self._on_key_press)
        self.connect('focus-out-event', self._on_focus_out)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.get_style_context().add_class('xattendo-card')
        card.set_size_request(360, -1)
        self.add(card)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=11)
        body.get_style_context().add_class('xattendo-card-body')
        card.pack_start(body, True, True, 0)

        # 1. Header: [42] Logtime / login, host, sid  ---  [● Active] [📌] [↻]
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        badge_42 = Gtk.Label(label='42')
        badge_42.get_style_context().add_class('xattendo-badge-42')
        badge_42.set_valign(Gtk.Align.CENTER)
        header.pack_start(badge_42, False, False, 0)

        title_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.title_lbl = Gtk.Label(xalign=0)
        self.title_lbl.get_style_context().add_class('xattendo-title')
        self.version_lbl = Gtk.Label(label=f'v{__version__}')
        self.version_lbl.set_direction(Gtk.TextDirection.LTR)
        self.version_lbl.set_valign(Gtk.Align.CENTER)
        self.version_lbl.get_style_context().add_class('xattendo-version-tag')
        title_row.pack_start(self.title_lbl, False, False, 0)
        title_row.pack_start(self.version_lbl, False, False, 0)

        self.sub_lbl = Gtk.Label(label='—', xalign=0)
        self.sub_lbl.set_direction(Gtk.TextDirection.LTR)
        self.sub_lbl.get_style_context().add_class('xattendo-subtitle')
        title_col.pack_start(title_row, False, False, 0)
        title_col.pack_start(self.sub_lbl, False, False, 0)
        header.pack_start(title_col, True, True, 0)

        self.refresh_icon = HeaderIcon('refresh', size=15)
        self.refresh_icon_btn = Gtk.Button()
        self.refresh_icon_btn.add(self.refresh_icon)
        self.refresh_icon_btn.get_style_context().add_class('xattendo-header-icon-btn')
        self.refresh_icon_btn.set_valign(Gtk.Align.CENTER)
        self.refresh_icon_btn.connect('clicked', lambda *_: self.on_refresh())
        header.pack_end(self.refresh_icon_btn, False, False, 0)

        self.pin_icon = HeaderIcon('pin', size=15)
        self.pin_icon_btn = Gtk.Button()
        self.pin_icon_btn.add(self.pin_icon)
        self.pin_icon_btn.get_style_context().add_class('xattendo-header-icon-btn')
        self.pin_icon_btn.set_valign(Gtk.Align.CENTER)
        self.pin_icon_btn.connect('clicked', self._on_pin_clicked)
        header.pack_end(self.pin_icon_btn, False, False, 0)

        self.status_pill = Gtk.Label(label='● Active')
        self.status_pill.get_style_context().add_class('xattendo-status-pill')
        self.status_pill.set_valign(Gtk.Align.CENTER)
        header.pack_end(self.status_pill, False, False, 2)

        body.pack_start(header, False, False, 0)

        # 2. Content Stack: 'overview' | 'sessions' | 'update'
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.stack.set_vhomogeneous(False)
        self.stack.add_named(self._build_overview_page(), 'overview')
        self.stack.add_named(self._build_sessions_page(), 'sessions')
        self.stack.add_named(self._build_update_page(), 'update')
        body.pack_start(self.stack, True, True, 0)

        # 3. Bottom Tab Navigation Bar: Overview | Sessions | Settings
        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        nav.set_homogeneous(True)
        nav.get_style_context().add_class('xattendo-bottom-nav')

        self.nav_overview_btn = Gtk.Button()
        self.nav_overview_btn.get_style_context().add_class('xattendo-nav-btn')
        self.nav_overview_btn.connect('clicked', lambda *_: self._switch_page('overview'))

        self.nav_sessions_btn = Gtk.Button()
        self.nav_sessions_btn.get_style_context().add_class('xattendo-nav-btn')
        self.nav_sessions_btn.connect('clicked', lambda *_: self._switch_page('sessions'))

        self.nav_settings_btn = Gtk.Button()
        self.nav_settings_btn.get_style_context().add_class('xattendo-nav-btn')
        self.nav_settings_btn.connect('clicked', self._on_settings_clicked)

        nav.pack_start(self.nav_overview_btn, True, True, 0)
        nav.pack_start(self.nav_sessions_btn, True, True, 0)
        nav.pack_start(self.nav_settings_btn, True, True, 0)
        card.pack_end(nav, False, False, 0)

        self._update_nav_buttons()
        self.apply_language(self.config_service.config.language)

    def _build_overview_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        # Optional Update Banner (shown only when non-mandatory update is available)
        self.update_banner_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.update_banner_box.get_style_context().add_class('xattendo-update-banner')
        self.update_banner_box.set_no_show_all(True)
        self.update_banner_lbl = Gtk.Label(xalign=0)
        self.update_banner_lbl.get_style_context().add_class('xattendo-field-label')
        self.update_banner_btn = Gtk.Button()
        self.update_banner_btn.get_style_context().add_class('xattendo-btn-primary')
        self.update_banner_btn.connect('clicked', lambda *_: self._start_update())
        self.update_banner_box.pack_start(self.update_banner_lbl, True, True, 0)
        self.update_banner_box.pack_end(self.update_banner_btn, False, False, 0)
        page.pack_start(self.update_banner_box, False, False, 0)

        # Hero Panel: Today's active time + clock + bar + pace ETA + timeline + 3 inset cards
        self.hero_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.hero_panel.get_style_context().add_class('xattendo-panel')

        hero_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.hero_title_lbl = Gtk.Label(xalign=0)
        self.hero_title_lbl.get_style_context().add_class('xattendo-panel-label')
        self.hero_ratio_lbl = Gtk.Label(label='', xalign=1)
        self.hero_ratio_lbl.set_direction(Gtk.TextDirection.LTR)
        self.hero_ratio_lbl.set_no_show_all(True)
        self.hero_ratio_lbl.get_style_context().add_class('xattendo-panel-label')
        hero_top.pack_start(self.hero_title_lbl, True, True, 0)
        hero_top.pack_end(self.hero_ratio_lbl, False, False, 0)
        self.hero_panel.pack_start(hero_top, False, False, 0)

        hero_clock_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.hero_clock = Gtk.Label(label='00:00:00', xalign=0)
        self.hero_clock.set_direction(Gtk.TextDirection.LTR)
        self.hero_clock.get_style_context().add_class('xattendo-hero-clock')
        self.hero_eta_badge = Gtk.Label(label='', xalign=1)
        self.hero_eta_badge.set_direction(Gtk.TextDirection.LTR)
        self.hero_eta_badge.set_no_show_all(True)
        self.hero_eta_badge.set_valign(Gtk.Align.CENTER)
        self.hero_eta_badge.get_style_context().add_class('xattendo-eta-badge')
        hero_clock_row.pack_start(self.hero_clock, True, True, 0)
        hero_clock_row.pack_end(self.hero_eta_badge, False, False, 0)
        self.hero_panel.pack_start(hero_clock_row, False, False, 0)

        self.daily_progress = Gtk.ProgressBar()
        self.daily_progress.get_style_context().add_class('xattendo-progress')
        self.hero_panel.pack_start(self.daily_progress, False, False, 0)

        self.pace_lbl = Gtk.Label(xalign=0)
        self.pace_lbl.set_line_wrap(True)
        self.pace_lbl.set_max_width_chars(42)
        self.pace_lbl.get_style_context().add_class('xattendo-pace-text')
        self.hero_panel.pack_start(self.pace_lbl, False, False, 0)

        self.timeline_widget = DayTimeline()
        self.hero_panel.pack_start(self.timeline_widget, False, False, 2)

        stats_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        stats_grid.set_homogeneous(True)
        cur_col, self.cur_sess_lbl, self.cur_sess_val = self._build_inset_stat('xattendo-stat-green')
        gross_col, self.gross_lbl, self.gross_val = self._build_inset_stat(None)
        locked_col, self.locked_lbl, self.locked_val = self._build_inset_stat('xattendo-stat-amber')
        stats_grid.pack_start(cur_col, True, True, 0)
        stats_grid.pack_start(gross_col, True, True, 0)
        stats_grid.pack_start(locked_col, True, True, 0)
        self.hero_panel.pack_start(stats_grid, False, False, 0)

        page.pack_start(self.hero_panel, False, False, 0)

        # Attendo Period Panel
        period_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        period_panel.get_style_context().add_class('xattendo-panel')

        p_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.period_range_lbl = Gtk.Label(xalign=0)
        self.period_range_lbl.get_style_context().add_class('xattendo-panel-label')
        self.period_status_lbl = Gtk.Label(label='0%', xalign=1)
        self.period_status_lbl.get_style_context().add_class('xattendo-pct-pill')
        p_top.pack_start(self.period_range_lbl, True, True, 0)
        p_top.pack_end(self.period_status_lbl, False, False, 0)
        period_panel.pack_start(p_top, False, False, 0)

        self.period_progress = Gtk.ProgressBar()
        self.period_progress.get_style_context().add_class('xattendo-progress')
        period_panel.pack_start(self.period_progress, False, False, 0)

        p_foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.period_net_lbl = Gtk.Label(label='0m of 30h', xalign=0)
        self.period_net_lbl.set_direction(Gtk.TextDirection.LTR)
        self.period_net_lbl.get_style_context().add_class('xattendo-mono-sm')
        self.period_left_lbl = Gtk.Label(label='30h left', xalign=1)
        self.period_left_lbl.set_direction(Gtk.TextDirection.LTR)
        self.period_left_lbl.set_no_show_all(True)
        self.period_left_lbl.get_style_context().add_class('xattendo-hint')
        p_foot.pack_start(self.period_net_lbl, True, True, 0)
        p_foot.pack_end(self.period_left_lbl, False, False, 0)
        period_panel.pack_start(p_foot, False, False, 0)

        page.pack_start(period_panel, False, False, 0)

        # Bottom 2-Column Panels: 42 Intra | 1337 Attendo
        bottom_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bottom_grid.set_homogeneous(True)

        # Left: 42 Intra
        intra_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        intra_card.get_style_context().add_class('xattendo-mini-card')
        intra_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.intra_title_lbl = Gtk.Label(xalign=0)
        self.intra_title_lbl.get_style_context().add_class('xattendo-panel-label')
        self.intra_link_btn = Gtk.Button(label='Link ↗')
        self.intra_link_btn.get_style_context().add_class('xattendo-link-btn')
        self.intra_link_btn.set_no_show_all(True)
        self.intra_link_btn.connect('clicked', lambda *_: self._open_link('intra', INTRA_PROFILE_URL))
        intra_top.pack_start(self.intra_title_lbl, True, True, 0)
        intra_top.pack_end(self.intra_link_btn, False, False, 0)
        intra_card.pack_start(intra_top, False, False, 0)

        self.intra_val_lbl = Gtk.Label(label='—', xalign=0)
        self.intra_val_lbl.set_direction(Gtk.TextDirection.LTR)
        self.intra_val_lbl.get_style_context().add_class('xattendo-big-metric')
        intra_card.pack_start(self.intra_val_lbl, False, False, 0)

        self.intra_sub_lbl = Gtk.Label(xalign=0)
        self.intra_sub_lbl.get_style_context().add_class('xattendo-hint')
        intra_card.pack_start(self.intra_sub_lbl, False, False, 0)

        # Right: 1337 Attendo
        attendo_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        attendo_card.get_style_context().add_class('xattendo-mini-card')
        att_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.attendo_title_lbl = Gtk.Label(xalign=0)
        self.attendo_title_lbl.get_style_context().add_class('xattendo-panel-label')
        self.attendo_link_btn = Gtk.Button(label='Link ↗')
        self.attendo_link_btn.get_style_context().add_class('xattendo-link-btn')
        self.attendo_link_btn.set_no_show_all(True)
        self.attendo_link_btn.connect('clicked', lambda *_: self._open_link('attendo', ATTENDO_LOGIN_URL))
        att_top.pack_start(self.attendo_title_lbl, True, True, 0)
        att_top.pack_end(self.attendo_link_btn, False, False, 0)
        attendo_card.pack_start(att_top, False, False, 0)

        self.attendo_val_lbl = Gtk.Label(label='—', xalign=0)
        self.attendo_val_lbl.set_direction(Gtk.TextDirection.LTR)
        self.attendo_val_lbl.get_style_context().add_class('xattendo-big-metric')
        attendo_card.pack_start(self.attendo_val_lbl, False, False, 0)

        self.attendo_days_lbl = Gtk.Label(xalign=0)
        self.attendo_days_lbl.get_style_context().add_class('xattendo-hint')
        attendo_card.pack_start(self.attendo_days_lbl, False, False, 0)

        self.days_bar = CountedDaysBar()
        attendo_card.pack_start(self.days_bar, False, False, 2)

        bottom_grid.pack_start(intra_card, True, True, 0)
        bottom_grid.pack_start(attendo_card, True, True, 0)
        page.pack_start(bottom_grid, False, False, 0)

        return page

    def _build_sessions_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        # Week & Month summary
        summary_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        summary_grid.set_homogeneous(True)
        self.week_title_lbl, self.week_hours_lbl, self.week_clock_lbl, week_card = self._build_mini_summary()
        self.month_title_lbl, self.month_hours_lbl, self.month_clock_lbl, month_card = self._build_mini_summary()
        summary_grid.pack_start(week_card, True, True, 0)
        summary_grid.pack_start(month_card, True, True, 0)
        page.pack_start(summary_grid, False, False, 0)

        # Recent Sessions list
        sess_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sess_panel.get_style_context().add_class('xattendo-panel')
        self.sess_list_title = Gtk.Label(xalign=0)
        self.sess_list_title.get_style_context().add_class('xattendo-section-title')
        sess_panel.pack_start(self.sess_list_title, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(150)
        scrolled.set_max_content_height(190)
        self.sess_rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scrolled.add(self.sess_rows_box)
        sess_panel.pack_start(scrolled, True, True, 0)
        page.pack_start(sess_panel, True, True, 0)

        # Actions: Full History + Reload / Quit
        self.full_history_btn = Gtk.Button()
        self.full_history_btn.get_style_context().add_class('xattendo-btn')
        self.full_history_btn.connect('clicked', self._on_history_clicked)
        page.pack_start(self.full_history_btn, False, False, 0)

        app_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        app_row.set_homogeneous(True)
        self.reload_btn = Gtk.Button()
        self.reload_btn.get_style_context().add_class('xattendo-btn')
        self.reload_btn.connect('clicked', self._on_reload_clicked)
        self.quit_btn = Gtk.Button()
        self.quit_btn.get_style_context().add_class('xattendo-btn')
        self.quit_btn.get_style_context().add_class('xattendo-btn-danger')
        self.quit_btn.connect('clicked', self._on_quit_clicked)
        app_row.pack_start(self.reload_btn, True, True, 0)
        app_row.pack_start(self.quit_btn, True, True, 0)
        page.pack_start(app_row, False, False, 0)

        return page

    def _build_update_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=11)
        card.get_style_context().add_class('xattendo-update-card')

        icon = HeaderIcon('update', size=28)
        icon.set_halign(Gtk.Align.CENTER)
        icon.get_style_context().add_class('xattendo-stat-cyan')
        card.pack_start(icon, False, False, 2)

        self.update_req_title_lbl = Gtk.Label()
        self.update_req_title_lbl.set_halign(Gtk.Align.CENTER)
        self.update_req_title_lbl.get_style_context().add_class('xattendo-title')
        card.pack_start(self.update_req_title_lbl, False, False, 0)

        self.update_req_ver_pill = Gtk.Label(label=f'v{__version__}')
        self.update_req_ver_pill.set_direction(Gtk.TextDirection.LTR)
        self.update_req_ver_pill.set_halign(Gtk.Align.CENTER)
        self.update_req_ver_pill.get_style_context().add_class('xattendo-update-version-pill')
        card.pack_start(self.update_req_ver_pill, False, False, 0)

        self.update_req_desc_lbl = Gtk.Label()
        self.update_req_desc_lbl.set_line_wrap(True)
        self.update_req_desc_lbl.set_max_width_chars(38)
        self.update_req_desc_lbl.set_justify(Gtk.Justification.CENTER)
        self.update_req_desc_lbl.get_style_context().add_class('xattendo-hint')
        card.pack_start(self.update_req_desc_lbl, False, False, 0)

        self.update_notes_lbl = Gtk.Label(xalign=0)
        self.update_notes_lbl.set_line_wrap(True)
        self.update_notes_lbl.set_max_width_chars(38)
        self.update_notes_lbl.set_no_show_all(True)
        self.update_notes_lbl.get_style_context().add_class('xattendo-update-notes')
        card.pack_start(self.update_notes_lbl, False, False, 0)

        self.update_err_lbl = Gtk.Label()
        self.update_err_lbl.set_line_wrap(True)
        self.update_err_lbl.set_max_width_chars(38)
        self.update_err_lbl.set_justify(Gtk.Justification.CENTER)
        self.update_err_lbl.set_no_show_all(True)
        self.update_err_lbl.get_style_context().add_class('xattendo-update-error')
        card.pack_start(self.update_err_lbl, False, False, 0)

        self.force_update_btn = Gtk.Button()
        self.force_update_btn.get_style_context().add_class('xattendo-btn-primary')
        self.force_update_btn.connect('clicked', lambda *_: self._start_update())
        card.pack_start(self.force_update_btn, False, False, 4)

        page.pack_start(card, True, True, 0)
        return page

    def _build_inset_stat(self, extra_val_class: Optional[str]):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.get_style_context().add_class('xattendo-inset-card')
        lbl = Gtk.Label(xalign=0)
        lbl.get_style_context().add_class('xattendo-stat-label')
        val = Gtk.Label(label='00:00:00', xalign=0)
        val.set_direction(Gtk.TextDirection.LTR)
        val.get_style_context().add_class('xattendo-stat-val')
        if extra_val_class:
            val.get_style_context().add_class(extra_val_class)
        card.pack_start(lbl, False, False, 0)
        card.pack_start(val, False, False, 0)
        return (card, lbl, val)

    def _build_mini_summary(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.get_style_context().add_class('xattendo-mini-card')

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(xalign=0)
        title.get_style_context().add_class('xattendo-section-title')
        hours = Gtk.Label(label='0.00h', xalign=1)
        hours.set_direction(Gtk.TextDirection.LTR)
        hours.get_style_context().add_class('xattendo-pct-pill')
        top.pack_start(title, True, True, 0)
        top.pack_end(hours, False, False, 0)
        card.pack_start(top, False, False, 0)

        clock = Gtk.Label(label='00:00:00', xalign=0)
        clock.set_direction(Gtk.TextDirection.LTR)
        clock.get_style_context().add_class('xattendo-mini-clock')
        card.pack_start(clock, False, False, 0)
        return (title, hours, clock, card)

    def _lang(self) -> str:
        return self.config_service.config.language

    @property
    def is_force_update_active(self) -> bool:
        return bool(self._pending_update and self._pending_update.mandatory)

    def _switch_page(self, page_name: str) -> None:
        if self.is_force_update_active and page_name != 'update':
            return
        self._active_page = page_name
        self.stack.set_visible_child_name(page_name)
        self._update_nav_buttons()

    def set_pending_update(self, info: Optional[UpdateInfo]) -> None:
        self._pending_update = info
        mandatory = bool(info and info.mandatory)
        for btn in (self.nav_overview_btn, self.nav_sessions_btn, self.nav_settings_btn):
            btn.set_sensitive(not mandatory)

        if info is None:
            self.update_banner_box.hide()
            if self._active_page == 'update':
                self._switch_page('overview')
            return

        lang = self._lang()
        ver = info.version.lstrip('vV')
        if mandatory:
            self.update_banner_box.hide()
            self.update_req_ver_pill.set_text(f'v{__version__} → v{ver}')
            if info.notes:
                self.update_notes_lbl.set_text(info.notes)
                self.update_notes_lbl.show()
            else:
                self.update_notes_lbl.hide()
            if not self._updating:
                self.force_update_btn.set_label(tr(lang, 'update_now_btn', version=f'v{ver}'))
                self.force_update_btn.set_sensitive(True)
            self._active_page = 'update'
            update_page = self.stack.get_child_by_name('update')
            if update_page is not None:
                update_page.show_all()
            self.stack.set_visible_child_name('update')
            self._update_nav_buttons()
        else:
            self.update_banner_lbl.set_text(tr(lang, 'update_banner_text', version=f'v{ver}'))
            self.update_banner_btn.set_label(tr(lang, 'update_banner_btn'))
            self.update_banner_box.show()
            self.update_banner_box.show_all()
            if self._active_page == 'update':
                self._switch_page('overview')

    def _start_update(self) -> None:
        if self._updating or self._pending_update is None:
            return
        lang = self._lang()
        info = self._pending_update
        ver = info.version.lstrip('vV')

        if info.download_url.startswith('simulate://'):
            self.update_err_lbl.get_style_context().remove_class('xattendo-update-error')
            self.update_err_lbl.get_style_context().add_class('xattendo-stat-green')
            self.update_err_lbl.set_text(tr(lang, 'update_simulated_ok', version=f'v{ver}'))
            self.update_err_lbl.show()
            return

        if self.update_service is None:
            return

        self._updating = True
        self.force_update_btn.set_sensitive(False)
        self.update_banner_btn.set_sensitive(False)
        self.update_err_lbl.get_style_context().remove_class('xattendo-stat-green')
        self.update_err_lbl.get_style_context().add_class('xattendo-update-error')
        self.update_err_lbl.set_text(tr(lang, 'downloading_update'))
        self.update_err_lbl.show()

        self.update_service.download_and_apply_async(
            info.download_url,
            lambda ok, msg: GLib.idle_add(self._on_update_applied, ok, msg),
        )

    def _on_update_applied(self, ok: bool, msg: str) -> bool:
        lang = self._lang()
        self._updating = False
        if ok:
            self.update_err_lbl.get_style_context().remove_class('xattendo-update-error')
            self.update_err_lbl.get_style_context().add_class('xattendo-stat-green')
            self.update_err_lbl.set_text(tr(lang, 'updated_restarting'))
            self.update_err_lbl.show()
            GLib.timeout_add(400, self._trigger_restart)
        else:
            ver = self._pending_update.version.lstrip('vV') if self._pending_update else ''
            self.force_update_btn.set_label(tr(lang, 'update_retry_btn', version=f'v{ver}'))
            self.force_update_btn.set_sensitive(True)
            self.update_banner_btn.set_sensitive(True)
            self.update_err_lbl.set_text(tr(lang, 'update_failed', msg=msg))
            self.update_err_lbl.show()
        return False

    def _trigger_restart(self) -> bool:
        if self.on_restart_after_update:
            self.on_restart_after_update()
        elif self.update_service:
            self.update_service.restart_installed()
        return False

    def _update_nav_buttons(self) -> None:
        for btn, name in (
            (self.nav_overview_btn, 'overview'),
            (self.nav_sessions_btn, 'sessions'),
        ):
            ctx = btn.get_style_context()
            if self._active_page == name:
                ctx.add_class('active')
            else:
                ctx.remove_class('active')

    def apply_language(self, lang: str) -> None:
        apply_rtl_layout(
            self,
            is_rtl(lang),
            ltr_widgets=(
                self.version_lbl,
                self.sub_lbl,
                self.hero_ratio_lbl,
                self.hero_clock,
                self.hero_eta_badge,
                self.timeline_widget,
                self.cur_sess_val,
                self.gross_val,
                self.locked_val,
                self.period_net_lbl,
                self.period_left_lbl,
                self.intra_val_lbl,
                self.attendo_val_lbl,
                self.days_bar,
                self.week_hours_lbl,
                self.week_clock_lbl,
                self.month_hours_lbl,
                self.month_clock_lbl,
                self.update_req_ver_pill,
            ),
        )
        self.title_lbl.set_text(tr(lang, 'logtime_title'))
        self.hero_title_lbl.set_text("Today's active time" if lang == 'en' else tr(lang, 'todays_active_time'))
        self.cur_sess_lbl.set_text(tr(lang, 'current_sess'))
        self.gross_lbl.set_text(tr(lang, 'gross_today'))
        self.locked_lbl.set_text(tr(lang, 'locked_label'))
        self.intra_title_lbl.set_text('42 Intra' if lang == 'en' else tr(lang, 'intra_label'))
        self.attendo_title_lbl.set_text('1337 Attendo' if lang == 'en' else tr(lang, 'attendo_label'))
        self.intra_sub_lbl.set_text(tr(lang, 'today_lower'))
        self.week_title_lbl.set_text(tr(lang, 'this_week'))
        self.month_title_lbl.set_text(tr(lang, 'this_month'))
        self.sess_list_title.set_text(tr(lang, 'tab_sessions').upper())
        self.full_history_btn.set_label(tr(lang, 'open_full_history'))
        self.reload_btn.set_label(tr(lang, 'reload_app'))
        self.quit_btn.set_label(tr(lang, 'quit'))
        self.nav_overview_btn.set_label(tr(lang, 'tab_overview'))
        self.nav_sessions_btn.set_label(tr(lang, 'tab_sessions'))
        self.nav_settings_btn.set_label(tr(lang, 'tab_settings'))
        self.refresh_icon_btn.set_tooltip_text(tr(lang, 'refresh'))
        self.update_req_title_lbl.set_text(tr(lang, 'update_required_title'))
        self.update_req_desc_lbl.set_text(tr(lang, 'update_required_desc'))
        if self._pending_update is not None:
            self.set_pending_update(self._pending_update)
        self._update_pin_button()

    def _open_link(self, target: str, fallback_url: str) -> None:
        self.hide()
        if self.on_open_web_login is not None:
            self.on_open_web_login(target)
        else:
            self.on_open_url(fallback_url)

    def contains_screen_point(self, lx: int, ly: int) -> bool:
        if not self.get_visible():
            return False
        gdk_win = self.get_window()
        if gdk_win is not None:
            rect = gdk_win.get_frame_extents()
            return (rect.x <= lx <= rect.x + rect.width) and (rect.y <= ly <= rect.y + rect.height)
        px, py = self.get_position()
        pw, ph = self.get_size()
        return (px <= lx <= px + pw) and (py <= ly <= py + ph)

    def _update_pin_button(self) -> None:
        pinned = self.config_service.config.position_locked
        lang = self._lang()
        self.pin_icon_btn.set_tooltip_text(tr(lang, 'unpin_btn' if pinned else 'pin_btn'))
        self.pin_icon.set_active(pinned)
        ctx = self.pin_icon_btn.get_style_context()
        if pinned:
            ctx.add_class('pinned')
        else:
            ctx.remove_class('pinned')

    def _on_pin_clicked(self, _btn: Gtk.Button) -> None:
        self.config_service.config.position_locked = not self.config_service.config.position_locked
        self.config_service.save(notify=True)
        self._update_pin_button()

    def _on_focus_out(self, _widget, _event) -> bool:
        if not self.get_visible() or (time.monotonic() - self._opened_at) < 0.15:
            return False
        self.hide()
        return False

    def _on_key_press(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    def _on_settings_clicked(self, _btn: Gtk.Button) -> None:
        if self.is_force_update_active:
            return
        self.hide()
        self.on_open_settings()

    def _on_history_clicked(self, _btn: Gtk.Button) -> None:
        self.hide()
        self.on_open_history()

    def _on_reload_clicked(self, _btn: Gtk.Button) -> None:
        self.hide()
        if self.on_reload:
            self.on_reload()

    def _on_quit_clicked(self, _btn: Gtk.Button) -> None:
        self.hide()
        if self.on_quit:
            self.on_quit()
        else:
            Gtk.main_quit()

    def update_content(
        self,
        local: Optional[LocalTrackerSnapshot],
        linked: Optional[LinkedAccountsState],
        daily_done_at: Optional[str] = None,
    ) -> None:
        lang = self._lang()
        cfg = self.config_service.config
        if local is None:
            return

        cur = local.current_session
        parts = []
        if linked and linked.login:
            parts.append(linked.login)
        if cur:
            parts.append(cur.host.split('.')[0])
            parts.append(cur.session_id)
        self.sub_lbl.set_text(', '.join(parts) if parts else 'x11')

        # Status pill
        s_ctx = self.status_pill.get_style_context()
        s_ctx.remove_class('status-active')
        s_ctx.remove_class('status-locked')
        locked_now = bool(cur and cur.live and cur.locked_now)
        if cur and cur.live:
            if locked_now:
                s_ctx.add_class('status-locked')
                self.status_pill.set_text(f"● {tr(lang, 'status_locked').capitalize()}")
            else:
                s_ctx.add_class('status-active')
                self.status_pill.set_text(f"● {tr(lang, 'status_active').capitalize()}")
        else:
            self.status_pill.set_text(f"● {tr(lang, 'status_idle').capitalize()}")

        # Hero Today
        today_net, today_gross, today_locked = compute_effective_today_metrics(local, linked)
        cur_net = cur.net_sec if cur else 0.0
        daily = calculate_daily_average_target(
            local,
            linked,
            today_net,
            fallback_target_hours=cfg.period_target_hours,
        )

        self.hero_clock.set_text(format_hms(today_net))
        if daily.daily_target_seconds > 0:
            self.hero_ratio_lbl.set_text(
                tr(
                    lang,
                    'active_of_target',
                    logged=format_compact_hours(today_net),
                    target=format_compact_hours(daily.daily_target_seconds),
                )
            )
            self.hero_ratio_lbl.show()
        else:
            self.hero_ratio_lbl.set_text('')
            self.hero_ratio_lbl.hide()
        self.daily_progress.set_fraction(daily.fraction)
        dp_ctx = self.daily_progress.get_style_context()
        eta_ctx = self.hero_eta_badge.get_style_context()
        eta_ts: Optional[float] = None
        if daily.done:
            dp_ctx.add_class('complete')
            eta_ctx.add_class('done')
            if daily_done_at:
                self.hero_eta_badge.set_text(tr(lang, 'goal_done_at_badge', time=daily_done_at))
                done_txt = tr(lang, 'pace_done_at_text', time=daily_done_at)
            else:
                self.hero_eta_badge.set_text(tr(lang, 'daily_done_badge'))
                done_txt = tr(lang, 'pace_done_text')
            self.hero_eta_badge.show()
            self.pace_lbl.set_markup(f"<span foreground='#34d399'><b>{done_txt}</b></span>")
        elif locked_now:
            dp_ctx.remove_class('complete')
            eta_ctx.remove_class('done')
            self.hero_eta_badge.hide()
            self.pace_lbl.set_markup(
                tr(lang, 'pace_locked_markup', left=format_hm(daily.remaining_today_seconds))
            )
        else:
            dp_ctx.remove_class('complete')
            eta_ctx.remove_class('done')
            eta_str = format_eta_clock(local.now_ts, daily.remaining_today_seconds)
            if daily.daily_target_seconds > 0:
                self.hero_eta_badge.set_text(tr(lang, 'goal_eta_badge', eta=eta_str))
                self.hero_eta_badge.show()
                eta_ts = local.now_ts + daily.remaining_today_seconds
            else:
                self.hero_eta_badge.hide()
            self.pace_lbl.set_markup(
                tr(lang, 'pace_eta_markup', left=format_hm(daily.remaining_today_seconds), eta=eta_str)
            )

        # Timeline
        w_start, w_end, segs, now_ts = build_day_active_segments(local)
        self.timeline_widget.set_timeline(w_start, w_end, segs, now_ts, eta_ts=eta_ts)

        # 3 Inset cards
        self.cur_sess_val.set_text(format_hms(cur_net))
        self.gross_val.set_text(format_hms(today_gross))
        self.locked_val.set_text(format_hms(today_locked))

        # Attendo Period Panel
        p_net, target_h, p_start, p_end, pct, left_h = merge_period_progress(
            local.period.net_seconds,
            today_net,
            linked,
            fallback_target_hours=cfg.period_target_hours,
            default_start=local.period_start,
            default_end=local.period_end,
        )
        p_hours = p_net / 3600.0
        target_fmt = format_compact_hours(target_h * 3600.0)
        self.period_range_lbl.set_text(
            tr(lang, 'attendo_period_range', start=p_start[5:10] if p_start else '—', end=p_end[5:10] if p_end else '—')
        )
        self.period_progress.set_fraction(max(0.0, min(1.0, pct / 100.0)))
        pp_ctx = self.period_progress.get_style_context()
        ps_ctx = self.period_status_lbl.get_style_context()
        if p_hours >= target_h:
            pp_ctx.add_class('complete')
            ps_ctx.add_class('xattendo-stat-green')
            self.period_status_lbl.set_text(tr(lang, 'goal_reached_text'))
        else:
            pp_ctx.remove_class('complete')
            ps_ctx.remove_class('xattendo-stat-green')
            self.period_status_lbl.set_text(f'{pct:.0f}%')

        self.period_net_lbl.set_text(
            tr(lang, 'active_of_target', logged=format_compact_hours(p_net), target=target_fmt)
        )
        if p_hours >= target_h or left_h <= 0.0:
            self.period_left_lbl.set_text('')
            self.period_left_lbl.hide()
        else:
            self.period_left_lbl.set_text(f"{format_compact_hours(left_h * 3600.0)} {tr(lang, 'period_left')}")
            self.period_left_lbl.show()

        # Bottom 2-Col: 42 Intra | 1337 Attendo
        if linked and linked.intra_linked:
            self.intra_val_lbl.set_text(format_compact_hours(linked.intra_today_seconds))
            self.intra_sub_lbl.set_text(tr(lang, 'today_lower'))
            self.intra_link_btn.hide()
        else:
            self.intra_val_lbl.set_text('—')
            self.intra_sub_lbl.set_text(tr(lang, 'not_linked_badge'))
            self.intra_link_btn.set_label(tr(lang, 'link_btn'))
            self.intra_link_btn.show()

        if linked and linked.attendo_linked and linked.current_period:
            cp = linked.current_period
            self.attendo_val_lbl.set_text(format_compact_hours(cp.total * 3600.0))
            self.attendo_days_lbl.set_text(tr(lang, 'days_of_seven', counted=cp.counted_days))
            self.days_bar.set_days(cp.counted_days, 7)
            self.attendo_link_btn.hide()
        else:
            self.attendo_val_lbl.set_text('—')
            self.attendo_days_lbl.set_text(tr(lang, 'not_linked_badge'))
            self.days_bar.set_days(0, 7)
            self.attendo_link_btn.set_label(tr(lang, 'link_btn'))
            self.attendo_link_btn.show()

        # Sessions Tab
        week_sec = max(local.week.net_seconds, float(linked.intra_week_seconds or 0.0) if linked else 0.0)
        month_sec = max(local.month.net_seconds, float(linked.intra_month_seconds or 0.0) if linked else 0.0)
        self.week_hours_lbl.set_text(format_compact_hours(week_sec))
        self.week_clock_lbl.set_text(format_hms(week_sec))
        self.month_hours_lbl.set_text(format_compact_hours(month_sec))
        self.month_clock_lbl.set_text(format_hms(month_sec))
        self._render_sessions_tab(local, lang)

    def _render_sessions_tab(self, local: LocalTrackerSnapshot, lang: str) -> None:
        for child in self.sess_rows_box.get_children():
            self.sess_rows_box.remove(child)
        for s in local.recent_sessions[:6]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.get_style_context().add_class('xattendo-inset-card')
            d_str = datetime.datetime.fromtimestamp(s.start_ts).strftime('%m-%d %H:%M')
            host_s = s.host.split('.')[0]
            left = Gtk.Label(label=f'{d_str} · {host_s}', xalign=0)
            left.set_direction(Gtk.TextDirection.LTR)
            left.get_style_context().add_class('xattendo-hint')
            right = Gtk.Label(label=format_hms(s.net_sec), xalign=1)
            right.set_direction(Gtk.TextDirection.LTR)
            right.get_style_context().add_class('xattendo-stat-val')
            if s.live:
                right.get_style_context().add_class('xattendo-stat-green')
            row.pack_start(left, True, True, 0)
            row.pack_end(right, False, False, 0)
            self.sess_rows_box.pack_start(row, False, False, 0)
        self.sess_rows_box.show_all()

    def position_near(self, anchor_window: Gtk.Window) -> None:
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geo = monitor.get_geometry()
        wa = monitor.get_workarea()
        panel_bottom = wa.y if wa.y > geo.y else geo.y + 28

        if hasattr(anchor_window, 'get_screen_rect'):
            px, py, pw, ph = anchor_window.get_screen_rect()
        else:
            px, py = anchor_window.get_position()
            pw, ph = anchor_window.get_size()
        mw, mh = self.get_size()

        centered_x = px + (pw - mw) // 2
        target_x = max(geo.x + 8, min(centered_x, geo.x + geo.width - mw - 8))
        target_y = max(panel_bottom + 6, py + ph + 8)
        if target_y + mh > geo.y + geo.height - 8:
            target_y = max(panel_bottom + 6, py - mh - 8)
        self.move(target_x, target_y)

    def toggle_near(
        self,
        anchor_window: Gtk.Window,
        local: Optional[LocalTrackerSnapshot],
        linked: Optional[LinkedAccountsState],
    ) -> None:
        if self.get_visible():
            self.hide()
            return
        self.update_content(local, linked)
        self._opened_at = time.monotonic()
        self.show_all()
        self.update_content(local, linked)
        self.position_near(anchor_window)
        self.present()
