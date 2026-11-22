"""42 Logtime-style dark card popup anchored near the floating/top-bar pill."""

import time
from typing import Callable, Optional

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gtk

from xattendo_widget.constants import ATTENDO_LOGIN_URL, ATTENDO_PROFILE_URL, INTRA_PROFILE_URL
from xattendo_widget.core.calculator import (
    calculate_daily_average_target,
    compute_effective_today_metrics,
    format_compact_hours,
    format_dec_hours,
    format_hm,
    format_hms,
    merge_period_progress,
)
from xattendo_widget.i18n import is_rtl, tr
from xattendo_widget.models import LinkedAccountsState, LocalTrackerSnapshot
from xattendo_widget.services.config_service import ConfigService
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
    ) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.config_service = config_service
        self.on_open_settings = on_open_settings
        self.on_open_history = on_open_history
        self.on_open_url = on_open_url
        self.on_refresh = on_refresh
        self.on_reload = on_reload
        self.on_quit = on_quit
        self._opened_at: float = 0.0

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

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.get_style_context().add_class('xattendo-card')
        card.set_size_request(344, -1)
        self.add(card)

        # 1. Header: [42] Logtime / host • sid  ---  [● ACTIVE] [↻] [✕]
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        badge_42 = Gtk.Label(label='42')
        badge_42.get_style_context().add_class('xattendo-badge-42')
        badge_42.set_valign(Gtk.Align.CENTER)
        header.pack_start(badge_42, False, False, 0)

        title_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.title_lbl = Gtk.Label(xalign=0)
        self.title_lbl.get_style_context().add_class('xattendo-title')
        self.sub_lbl = Gtk.Label(label='—', xalign=0)
        self.sub_lbl.set_direction(Gtk.TextDirection.LTR)
        self.sub_lbl.get_style_context().add_class('xattendo-subtitle')
        title_col.pack_start(self.title_lbl, False, False, 0)
        title_col.pack_start(self.sub_lbl, False, False, 0)
        header.pack_start(title_col, True, True, 0)

        close_btn = Gtk.Button(label='✕')
        close_btn.get_style_context().add_class('xattendo-icon-btn')
        close_btn.set_valign(Gtk.Align.CENTER)
        close_btn.connect('clicked', lambda *_: self.hide())
        header.pack_end(close_btn, False, False, 0)

        refresh_icon_btn = Gtk.Button(label='↻')
        refresh_icon_btn.get_style_context().add_class('xattendo-icon-btn')
        refresh_icon_btn.set_valign(Gtk.Align.CENTER)
        refresh_icon_btn.connect('clicked', lambda *_: self.on_refresh())
        header.pack_end(refresh_icon_btn, False, False, 0)

        self.status_pill = Gtk.Label(label='● ACTIVE')
        self.status_pill.get_style_context().add_class('xattendo-status-pill')
        self.status_pill.set_valign(Gtk.Align.CENTER)
        header.pack_end(self.status_pill, False, False, 2)

        card.pack_start(header, False, False, 0)

        # 2. Hero Card: TODAY'S ACTIVE TIME | 3.60h / 03:36:11 / Current Sess | Gross Today | Locked
        self.hero_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.hero_card.get_style_context().add_class('xattendo-hero-card')

        hero_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.hero_title_lbl = Gtk.Label(xalign=0)
        self.hero_title_lbl.get_style_context().add_class('xattendo-section-title')
        self.hero_dec_badge = Gtk.Label(label='0.00h', xalign=1)
        self.hero_dec_badge.set_direction(Gtk.TextDirection.LTR)
        self.hero_dec_badge.get_style_context().add_class('xattendo-decimal-badge')
        hero_top.pack_start(self.hero_title_lbl, True, True, 0)
        hero_top.pack_end(self.hero_dec_badge, False, False, 0)
        self.hero_card.pack_start(hero_top, False, False, 0)

        self.hero_clock = Gtk.Label(label='00:00:00', xalign=0)
        self.hero_clock.set_direction(Gtk.TextDirection.LTR)
        self.hero_clock.get_style_context().add_class('xattendo-hero-clock')
        self.hero_card.pack_start(self.hero_clock, False, False, 0)

        # Daily Average Target strip (hours_left / days_left)
        daily_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        daily_box.get_style_context().add_class('xattendo-daily-row')
        daily_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.daily_target_lbl = Gtk.Label(xalign=0)
        self.daily_target_lbl.get_style_context().add_class('xattendo-hint')
        self.daily_status_lbl = Gtk.Label(label='', xalign=1)
        self.daily_status_lbl.set_direction(Gtk.TextDirection.LTR)
        self.daily_status_lbl.get_style_context().add_class('xattendo-pct-pill')
        daily_top.pack_start(self.daily_target_lbl, True, True, 0)
        daily_top.pack_end(self.daily_status_lbl, False, False, 0)
        daily_box.pack_start(daily_top, False, False, 0)

        self.daily_progress = Gtk.ProgressBar()
        self.daily_progress.get_style_context().add_class('xattendo-progress')
        daily_box.pack_start(self.daily_progress, False, False, 0)
        self.hero_card.pack_start(daily_box, False, False, 2)

        divider = Gtk.Box()
        divider.get_style_context().add_class('xattendo-hero-divider')
        self.hero_card.pack_start(divider, False, False, 2)

        stats_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        stats_grid.set_homogeneous(True)

        cur_col, self.cur_sess_lbl, self.cur_sess_val = self._build_stat_col('xattendo-stat-green')
        gross_col, self.gross_lbl, self.gross_val = self._build_stat_col(None)
        locked_col, self.locked_lbl, self.locked_val = self._build_stat_col('xattendo-stat-amber')
        stats_grid.pack_start(cur_col, True, True, 0)
        stats_grid.pack_start(gross_col, True, True, 0)
        stats_grid.pack_start(locked_col, True, True, 0)
        self.hero_card.pack_start(stats_grid, False, False, 0)

        card.pack_start(self.hero_card, False, False, 0)

        # 3. Attendo Period Card
        period_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        period_card.get_style_context().add_class('xattendo-section')

        p_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.period_title_lbl = Gtk.Label(xalign=0)
        self.period_title_lbl.get_style_context().add_class('xattendo-section-title')
        self.period_dates_lbl = Gtk.Label(label='', xalign=0)
        self.period_dates_lbl.set_direction(Gtk.TextDirection.LTR)
        self.period_dates_lbl.get_style_context().add_class('xattendo-hint')
        self.period_pct_lbl = Gtk.Label(label='0%', xalign=1)
        self.period_pct_lbl.set_direction(Gtk.TextDirection.LTR)
        self.period_pct_lbl.get_style_context().add_class('xattendo-pct-pill')
        p_top.pack_start(self.period_title_lbl, False, False, 0)
        p_top.pack_start(self.period_dates_lbl, True, True, 4)
        p_top.pack_end(self.period_pct_lbl, False, False, 0)
        period_card.pack_start(p_top, False, False, 0)

        self.period_progress = Gtk.ProgressBar()
        self.period_progress.get_style_context().add_class('xattendo-progress')
        period_card.pack_start(self.period_progress, False, False, 2)

        p_foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.period_net_lbl = Gtk.Label(label='00:00:00 (0.00h / 30h)', xalign=0)
        self.period_net_lbl.set_direction(Gtk.TextDirection.LTR)
        self.period_net_lbl.get_style_context().add_class('xattendo-mono-sm')
        self.period_left_lbl = Gtk.Label(label='30.00h left', xalign=1)
        self.period_left_lbl.set_direction(Gtk.TextDirection.LTR)
        self.period_left_lbl.get_style_context().add_class('xattendo-hint')
        p_foot.pack_start(self.period_net_lbl, True, True, 0)
        p_foot.pack_end(self.period_left_lbl, False, False, 0)
        period_card.pack_start(p_foot, False, False, 0)

        card.pack_start(period_card, False, False, 0)

        # 4. Linked Accounts Row: 42 INTRA | 1337 ATTENDO
        accounts_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        accounts_grid.set_homogeneous(True)

        self.intra_card, self.intra_title_lbl, self.intra_val_lbl, self.intra_link_btn = (
            self._build_account_card(INTRA_PROFILE_URL)
        )
        self.attendo_card, self.attendo_title_lbl, self.attendo_val_lbl, self.attendo_link_btn = (
            self._build_account_card(ATTENDO_LOGIN_URL, open_url_if_linked=ATTENDO_PROFILE_URL)
        )
        accounts_grid.pack_start(self.intra_card, True, True, 0)
        accounts_grid.pack_start(self.attendo_card, True, True, 0)
        card.pack_start(accounts_grid, False, False, 0)

        # 5. Summary Grid: THIS WEEK | THIS MONTH
        summary_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        summary_grid.set_homogeneous(True)
        self.week_title_lbl, self.week_hours_lbl, self.week_clock_lbl, week_card = self._build_mini_summary()
        self.month_title_lbl, self.month_hours_lbl, self.month_clock_lbl, month_card = self._build_mini_summary()
        summary_grid.pack_start(week_card, True, True, 0)
        summary_grid.pack_start(month_card, True, True, 0)
        card.pack_start(summary_grid, False, False, 0)

        # 6. Action Buttons
        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row1.set_homogeneous(True)
        self.history_btn = Gtk.Button()
        self.history_btn.get_style_context().add_class('xattendo-btn')
        self.history_btn.connect('clicked', self._on_history_clicked)
        self.pin_btn = Gtk.Button()
        self.pin_btn.get_style_context().add_class('xattendo-btn')
        self.pin_btn.connect('clicked', self._on_pin_clicked)
        row1.pack_start(self.history_btn, True, True, 0)
        row1.pack_start(self.pin_btn, True, True, 0)
        card.pack_start(row1, False, False, 0)

        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row2.set_homogeneous(True)
        self.settings_btn = Gtk.Button()
        self.settings_btn.get_style_context().add_class('xattendo-btn-primary')
        self.settings_btn.connect('clicked', self._on_settings_clicked)
        self.reload_btn = Gtk.Button()
        self.reload_btn.get_style_context().add_class('xattendo-btn')
        self.reload_btn.connect('clicked', self._on_reload_clicked)
        self.quit_btn = Gtk.Button()
        self.quit_btn.get_style_context().add_class('xattendo-btn')
        self.quit_btn.get_style_context().add_class('xattendo-btn-danger')
        self.quit_btn.connect('clicked', self._on_quit_clicked)
        row2.pack_start(self.settings_btn, True, True, 0)
        row2.pack_start(self.reload_btn, True, True, 0)
        row2.pack_start(self.quit_btn, True, True, 0)
        card.pack_start(row2, False, False, 0)

        self.apply_language(self.config_service.config.language)

    def _build_stat_col(self, extra_val_class: Optional[str]):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        lbl = Gtk.Label(xalign=0)
        lbl.get_style_context().add_class('xattendo-stat-label')
        val = Gtk.Label(label='00:00:00', xalign=0)
        val.set_direction(Gtk.TextDirection.LTR)
        val.get_style_context().add_class('xattendo-stat-val')
        if extra_val_class:
            val.get_style_context().add_class(extra_val_class)
        col.pack_start(lbl, False, False, 0)
        col.pack_start(val, False, False, 0)
        return (col, lbl, val)

    def _build_account_card(self, login_url: str, open_url_if_linked: Optional[str] = None):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        card.get_style_context().add_class('xattendo-mini-card')

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(xalign=0)
        title.get_style_context().add_class('xattendo-section-title')
        link_btn = Gtk.Button(label='Link ↗')
        link_btn.get_style_context().add_class('xattendo-link-btn')
        link_btn.connect(
            'clicked',
            lambda *_: self.on_open_url(open_url_if_linked or login_url),
        )
        top.pack_start(title, True, True, 0)
        top.pack_end(link_btn, False, False, 0)
        card.pack_start(top, False, False, 0)

        val = Gtk.Label(label='—', xalign=0)
        val.set_direction(Gtk.TextDirection.LTR)
        val.get_style_context().add_class('xattendo-mono-sm')
        card.pack_start(val, False, False, 0)
        return (card, title, val, link_btn)

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

    def apply_language(self, lang: str) -> None:
        apply_rtl_layout(
            self,
            is_rtl(lang),
            ltr_widgets=(
                self.sub_lbl,
                self.hero_dec_badge,
                self.hero_clock,
                self.daily_status_lbl,
                self.cur_sess_val,
                self.gross_val,
                self.locked_val,
                self.period_dates_lbl,
                self.period_pct_lbl,
                self.period_net_lbl,
                self.period_left_lbl,
                self.intra_val_lbl,
                self.attendo_val_lbl,
                self.week_hours_lbl,
                self.week_clock_lbl,
                self.month_hours_lbl,
                self.month_clock_lbl,
            ),
        )
        self.title_lbl.set_text(tr(lang, 'logtime_title'))
        self.hero_title_lbl.set_text(tr(lang, 'todays_active_time'))
        self.cur_sess_lbl.set_text(tr(lang, 'current_sess'))
        self.gross_lbl.set_text(tr(lang, 'gross_today'))
        self.locked_lbl.set_text(tr(lang, 'locked_label'))
        self.period_title_lbl.set_text(tr(lang, 'attendo_period'))
        self.intra_title_lbl.set_text(tr(lang, 'intra_label'))
        self.attendo_title_lbl.set_text(tr(lang, 'attendo_label'))
        self.week_title_lbl.set_text(tr(lang, 'this_week'))
        self.month_title_lbl.set_text(tr(lang, 'this_month'))
        self.history_btn.set_label(tr(lang, 'history_sessions_btn'))
        self.settings_btn.set_label(tr(lang, 'settings'))
        self.reload_btn.set_label(tr(lang, 'reload_app'))
        self.quit_btn.set_label(tr(lang, 'quit'))
        self._update_pin_button()

    def _update_pin_button(self) -> None:
        pinned = self.config_service.config.position_locked
        lang = self._lang()
        self.pin_btn.set_label(tr(lang, 'unpin_btn' if pinned else 'pin_btn'))
        ctx = self.pin_btn.get_style_context()
        if pinned:
            ctx.add_class('xattendo-btn-pinned')
        else:
            ctx.remove_class('xattendo-btn-pinned')

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
    ) -> None:
        lang = self._lang()
        cfg = self.config_service.config

        if local is None:
            return

        cur = local.current_session
        login_prefix = f'{linked.login} · ' if (linked and linked.login) else ''
        if cur:
            short_host = cur.host.split('.')[0]
            self.sub_lbl.set_text(f'{login_prefix}{short_host} • {cur.session_id}')
        else:
            self.sub_lbl.set_text(f'{login_prefix}x11')

        # Status pill
        s_ctx = self.status_pill.get_style_context()
        s_ctx.remove_class('status-active')
        s_ctx.remove_class('status-locked')
        if cur and cur.live:
            if cur.locked_now:
                s_ctx.add_class('status-locked')
                self.status_pill.set_text(f"● {tr(lang, 'status_locked')}")
            else:
                s_ctx.add_class('status-active')
                self.status_pill.set_text(f"● {tr(lang, 'status_active')}")
        else:
            self.status_pill.set_text(f"● {tr(lang, 'status_idle')}")

        # Hero Today (fused with linked 42 Intra / Attendo when available)
        today_net, today_gross, today_locked = compute_effective_today_metrics(local, linked)
        cur_net = cur.net_sec if cur else 0.0

        self.hero_clock.set_text(format_hms(today_net))
        self.hero_dec_badge.set_text(format_dec_hours(today_net))
        self.cur_sess_val.set_text(format_hms(cur_net))
        self.gross_val.set_text(format_hms(today_gross))
        self.locked_val.set_text(format_hms(today_locked))

        # Daily Average Target (hours_left / days_left)
        daily = calculate_daily_average_target(
            local,
            linked,
            today_net,
            fallback_target_hours=cfg.period_target_hours,
        )
        formula = tr(
            lang,
            'daily_avg_formula',
            target=format_dec_hours(daily.daily_target_seconds),
            rem_h=f'{daily.remaining_period_hours:.1f}h',
            days=daily.remaining_days,
        )
        self.daily_target_lbl.set_text(f"{tr(lang, 'daily_target_label')}: {formula}")
        self.daily_progress.set_fraction(daily.fraction)

        dp_ctx = self.daily_progress.get_style_context()
        ds_ctx = self.daily_status_lbl.get_style_context()
        if daily.done:
            dp_ctx.add_class('complete')
            ds_ctx.add_class('xattendo-stat-green')
            self.daily_status_lbl.set_text(tr(lang, 'daily_done_badge'))
        else:
            dp_ctx.remove_class('complete')
            ds_ctx.remove_class('xattendo-stat-green')
            pct_int = int(round(daily.fraction * 100))
            self.daily_status_lbl.set_text(
                f"{tr(lang, 'daily_left_fmt', time=format_hm(daily.remaining_today_seconds))} · {pct_int}%"
            )

        # Period Progress
        p_net, target_h, p_start, p_end, pct, left_h = merge_period_progress(
            local.period.net_seconds,
            today_net,
            linked,
            fallback_target_hours=cfg.period_target_hours,
            default_start=local.period_start,
            default_end=local.period_end,
        )
        p_hours = p_net / 3600.0
        target_fmt = f'{int(target_h)}h' if target_h == int(target_h) else f'{target_h:.1f}h'
        if p_start and p_end:
            self.period_dates_lbl.set_text(f'{p_start[5:10]} → {p_end[5:10]}')
        else:
            self.period_dates_lbl.set_text('')
        self.period_pct_lbl.set_text(f'{pct:.0f}%')
        self.period_progress.set_fraction(max(0.0, min(1.0, pct / 100.0)))

        p_ctx = self.period_progress.get_style_context()
        h_ctx = self.hero_card.get_style_context()
        h_ctx.remove_class('goal-reached')
        h_ctx.remove_class('locked-mode')
        if p_hours >= target_h:
            p_ctx.add_class('complete')
        else:
            p_ctx.remove_class('complete')
        if daily.done:
            h_ctx.add_class('goal-reached')
        elif cur and cur.locked_now:
            h_ctx.add_class('locked-mode')

        self.period_net_lbl.set_text(f'{format_hms(p_net)} ({p_hours:.2f}h / {target_fmt})')
        self.period_left_lbl.set_text(f"{left_h:.2f}h {tr(lang, 'period_left')}")

        # Linked accounts row
        if linked and linked.intra_linked:
            self.intra_val_lbl.set_text(
                tr(lang, 'intra_today_fmt', hours=format_dec_hours(linked.intra_today_seconds))
            )
            self.intra_val_lbl.get_style_context().add_class('xattendo-stat-green')
            self.intra_link_btn.hide()
        else:
            self.intra_val_lbl.set_text(tr(lang, 'not_linked_badge'))
            self.intra_val_lbl.get_style_context().remove_class('xattendo-stat-green')
            self.intra_link_btn.set_label(tr(lang, 'link_btn'))
            self.intra_link_btn.show()

        if linked and linked.attendo_linked and linked.current_period:
            cp = linked.current_period
            if linked.attendo_recorded_today_seconds is not None and linked.attendo_recorded_today_seconds > 0:
                self.attendo_val_lbl.set_text(
                    tr(
                        lang,
                        'attendo_today_period_fmt',
                        today=format_compact_hours(linked.attendo_recorded_today_seconds),
                        period=format_compact_hours(cp.total * 3600.0),
                        counted=cp.counted_days,
                    )
                )
            else:
                self.attendo_val_lbl.set_text(
                    tr(
                        lang,
                        'attendo_period_fmt',
                        hours=format_dec_hours(cp.total * 3600.0),
                        counted=cp.counted_days,
                    )
                )
            self.attendo_val_lbl.get_style_context().add_class('xattendo-stat-green')
            self.attendo_link_btn.hide()
        else:
            self.attendo_val_lbl.set_text(tr(lang, 'not_linked_badge'))
            self.attendo_val_lbl.get_style_context().remove_class('xattendo-stat-green')
            self.attendo_link_btn.set_label(tr(lang, 'link_btn'))
            self.attendo_link_btn.show()

        # Week & Month (prefer max of local or Intra)
        week_sec = max(local.week.net_seconds, float(linked.intra_week_seconds or 0.0) if linked else 0.0)
        month_sec = max(local.month.net_seconds, float(linked.intra_month_seconds or 0.0) if linked else 0.0)
        self.week_hours_lbl.set_text(format_dec_hours(week_sec))
        self.week_clock_lbl.set_text(format_hms(week_sec))
        self.month_hours_lbl.set_text(format_dec_hours(month_sec))
        self.month_clock_lbl.set_text(format_hms(month_sec))

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
        # Re-apply conditional link button visibility after show_all
        self.update_content(local, linked)
        self.position_near(anchor_window)
        self.present()
