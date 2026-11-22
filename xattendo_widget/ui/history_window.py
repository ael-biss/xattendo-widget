"""Dedicated window for Local Sessions, Linked Attendo Periods, and Lock History."""

import datetime
from typing import Callable, List, Optional

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gtk

from xattendo_widget.core.calculator import (
    campus_today,
    compute_effective_today_metrics,
    format_compact_hours,
    format_hm,
    format_hms,
    merge_period_progress,
)
from xattendo_widget.i18n import is_rtl, tr
from xattendo_widget.models import LinkedAccountsState, LocalTrackerSnapshot
from xattendo_widget.services.config_service import ConfigService
from xattendo_widget.ui.styles import apply_rtl_layout, load_state_icon

SESSION_COLUMNS = [
    ('col_date', 96, True),
    ('col_host', 110, True),
    ('col_start', 82, True),
    ('col_end', 82, True),
    ('col_net', 88, True),
    ('col_locked', 88, True),
    ('col_gross', 88, True),
]

PERIOD_COLUMNS = [
    ('col_date', 120, True),
    ('col_period', 160, False),
    ('col_hours', 120, True),
    ('col_status', 120, False),
]

LOCK_COLUMNS = [
    ('col_locked_at', 110, True),
    ('col_unlocked_at', 110, True),
    ('col_duration', 110, True),
    ('col_status', 120, False),
]


class HistoryWindow(Gtk.Window):
    def __init__(
        self,
        config_service: ConfigService,
        on_refresh: Callable[[], None],
    ) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.config_service = config_service
        self.on_refresh = on_refresh
        self._local: Optional[LocalTrackerSnapshot] = None
        self._linked: Optional[LinkedAccountsState] = None
        self._active_tab: str = 'sessions'  # 'sessions' | 'periods' | 'locks'

        self.set_default_size(780, 560)
        self.set_resizable(True)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.get_style_context().add_class('xattendo-window')

        self.connect('delete-event', self._on_delete)
        self.connect('key-press-event', self._on_key_press)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_border_width(18)
        self.add(root)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        pixbuf = load_state_icon(24, 'normal')
        if pixbuf:
            header.pack_start(Gtk.Image.new_from_pixbuf(pixbuf), False, False, 0)

        title_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.title_lbl = Gtk.Label(xalign=0)
        self.title_lbl.get_style_context().add_class('xattendo-title')
        self.sub_lbl = Gtk.Label(xalign=0)
        self.sub_lbl.get_style_context().add_class('xattendo-subtitle')
        title_col.pack_start(self.title_lbl, False, False, 0)
        title_col.pack_start(self.sub_lbl, False, False, 0)
        header.pack_start(title_col, True, True, 0)

        self.refresh_btn = Gtk.Button()
        self.refresh_btn.get_style_context().add_class('xattendo-btn')
        self.refresh_btn.set_valign(Gtk.Align.CENTER)
        self.refresh_btn.connect('clicked', lambda *_: self.on_refresh())
        header.pack_end(self.refresh_btn, False, False, 0)

        self.close_btn = Gtk.Button()
        self.close_btn.get_style_context().add_class('xattendo-btn-primary')
        self.close_btn.set_valign(Gtk.Align.CENTER)
        self.close_btn.connect('clicked', lambda *_: self.hide())
        header.pack_end(self.close_btn, False, False, 4)
        root.pack_start(header, False, False, 0)

        # Tab switcher
        tabs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.tab_sessions_btn = Gtk.Button()
        self.tab_sessions_btn.get_style_context().add_class('xattendo-tab-btn')
        self.tab_sessions_btn.connect('clicked', lambda *_: self._switch_tab('sessions'))

        self.tab_periods_btn = Gtk.Button()
        self.tab_periods_btn.get_style_context().add_class('xattendo-tab-btn')
        self.tab_periods_btn.connect('clicked', lambda *_: self._switch_tab('periods'))

        self.tab_locks_btn = Gtk.Button()
        self.tab_locks_btn.get_style_context().add_class('xattendo-tab-btn')
        self.tab_locks_btn.connect('clicked', lambda *_: self._switch_tab('locks'))

        tabs.pack_start(self.tab_sessions_btn, False, False, 0)
        tabs.pack_start(self.tab_periods_btn, False, False, 0)
        tabs.pack_start(self.tab_locks_btn, False, False, 0)
        root.pack_start(tabs, False, False, 0)

        # Summary banner
        self.summary_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.summary_card.get_style_context().add_class('xattendo-section')
        self.summary_title = Gtk.Label(xalign=0)
        self.summary_title.get_style_context().add_class('xattendo-section-title')
        self.summary_detail = Gtk.Label(xalign=0)
        self.summary_detail.get_style_context().add_class('xattendo-field-label')
        self.summary_progress = Gtk.ProgressBar()
        self.summary_progress.get_style_context().add_class('xattendo-progress')
        self.summary_card.pack_start(self.summary_title, False, False, 0)
        self.summary_card.pack_start(self.summary_detail, False, False, 0)
        self.summary_card.pack_start(self.summary_progress, False, False, 2)
        root.pack_start(self.summary_card, False, False, 0)

        # Column headers
        self.hdr_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.hdr_row.get_style_context().add_class('xattendo-sched-header')
        root.pack_start(self.hdr_row, False, False, 0)

        # Scrollable rows
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        root.pack_start(scrolled, True, True, 0)

        self.rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        scrolled.add(self.rows_box)

        self.apply_language(self._lang())

    def _lang(self) -> str:
        return self.config_service.config.language

    def _switch_tab(self, tab: str) -> None:
        self._active_tab = tab
        self._render()

    def _on_key_press(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    def _on_delete(self, _widget, _event) -> bool:
        self.hide()
        return True

    def apply_language(self, lang: str) -> None:
        apply_rtl_layout(self, is_rtl(lang))
        self.set_title(tr(lang, 'history_win_title'))
        self.title_lbl.set_text(tr(lang, 'history_header_title'))
        self.tab_sessions_btn.set_label(tr(lang, 'tab_sessions'))
        self.tab_periods_btn.set_label(tr(lang, 'tab_periods'))
        self.tab_locks_btn.set_label(tr(lang, 'tab_locks'))
        self.refresh_btn.set_label(tr(lang, 'refresh'))
        self.close_btn.set_label(tr(lang, 'close'))
        self._render()

    def open_window(
        self,
        local: Optional[LocalTrackerSnapshot],
        linked: Optional[LinkedAccountsState],
    ) -> None:
        self._local = local
        self._linked = linked
        self.apply_language(self._lang())
        self.show_all()
        self.present()

    def update_data(
        self,
        local: Optional[LocalTrackerSnapshot],
        linked: Optional[LinkedAccountsState],
    ) -> None:
        self._local = local
        self._linked = linked
        if self.get_visible():
            self._render()

    def _render(self) -> None:
        lang = self._lang()
        for btn, tab_id in (
            (self.tab_sessions_btn, 'sessions'),
            (self.tab_periods_btn, 'periods'),
            (self.tab_locks_btn, 'locks'),
        ):
            ctx = btn.get_style_context()
            if self._active_tab == tab_id:
                ctx.add_class('active')
            else:
                ctx.remove_class('active')

        if self._linked and self._linked.login:
            self.sub_lbl.set_text(f'{self._linked.login} · {campus_today().isoformat()}')
        else:
            self.sub_lbl.set_text(tr(lang, 'history_header_sub_default'))

        cols = {
            'sessions': SESSION_COLUMNS,
            'periods': PERIOD_COLUMNS,
            'locks': LOCK_COLUMNS,
        }[self._active_tab]

        for child in self.hdr_row.get_children():
            self.hdr_row.remove(child)
        for key, width, _ in cols:
            lbl = Gtk.Label(label=tr(lang, key), xalign=0.5)
            lbl.set_size_request(width, -1)
            lbl.get_style_context().add_class('xattendo-sched-th')
            self.hdr_row.pack_start(lbl, True, True, 0)
        self.hdr_row.show_all()

        for child in self.rows_box.get_children():
            self.rows_box.remove(child)

        if self._active_tab == 'sessions':
            self._render_sessions(lang)
        elif self._active_tab == 'periods':
            self._render_periods(lang)
        else:
            self._render_locks(lang)

        self.rows_box.show_all()

    def _render_sessions(self, lang: str) -> None:
        local = self._local
        sessions = local.recent_sessions if local else []
        self.summary_title.set_text(tr(lang, 'tab_sessions').upper())
        if local:
            today_net, _today_gross, today_locked = compute_effective_today_metrics(local, self._linked)
            self.summary_detail.set_text(
                tr(
                    lang,
                    'sessions_summary_fmt',
                    net=format_hms(today_net),
                    locked=format_hms(today_locked),
                    count=len(sessions),
                )
            )
        else:
            self.summary_detail.set_text(tr(lang, 'no_sessions_data'))
        self.summary_progress.hide()

        if not sessions:
            lbl = Gtk.Label(label=tr(lang, 'no_sessions_data'))
            lbl.get_style_context().add_class('xattendo-hint')
            self.rows_box.pack_start(lbl, False, False, 20)
            return

        for idx, s in enumerate(sessions):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            rctx = row.get_style_context()
            rctx.add_class('xattendo-sched-row')
            if s.live:
                rctx.add_class('xattendo-sched-row-today')
            elif idx % 2 == 1:
                rctx.add_class('xattendo-sched-row-alt')

            date_s = datetime.datetime.fromtimestamp(s.start_ts).strftime('%Y-%m-%d')
            start_s = datetime.datetime.fromtimestamp(s.start_ts).strftime('%H:%M:%S')
            end_s = tr(lang, 'status_live') if s.live else datetime.datetime.fromtimestamp(s.end_ts).strftime('%H:%M:%S')
            host_s = s.host.split('.')[0]
            values = [
                date_s,
                host_s,
                start_s,
                end_s,
                format_hms(s.net_sec),
                format_hms(s.locked_sec),
                format_hms(s.gross_sec),
            ]
            ltr_cells: List[Gtk.Widget] = []
            for col_idx, val in enumerate(values):
                _, width, is_mono = SESSION_COLUMNS[col_idx]
                cell = Gtk.Label(label=val, xalign=0.5)
                if is_mono:
                    ltr_cells.append(cell)
                cell.set_size_request(width, -1)
                cell.get_style_context().add_class(
                    'xattendo-sched-cell-mono' if is_mono else 'xattendo-sched-cell'
                )
                row.pack_start(cell, True, True, 0)
            apply_rtl_layout(row, is_rtl(lang), ltr_widgets=ltr_cells)
            self.rows_box.pack_start(row, False, False, 0)

    def _render_periods(self, lang: str) -> None:
        linked = self._linked
        local = self._local
        periods = []
        if linked:
            if linked.current_period:
                periods.append(linked.current_period)
            if linked.previous_period:
                periods.append(linked.previous_period)

        local_p_sec = local.period.net_seconds if local else 0.0
        local_t_sec = compute_effective_today_metrics(local, linked)[0] if local else 0.0
        p_net, target_h, p_start, p_end, pct, _ = merge_period_progress(
            local_p_sec,
            local_t_sec,
            linked,
            fallback_target_hours=self.config_service.config.period_target_hours,
            default_start=local.period_start if local else '',
            default_end=local.period_end if local else '',
        )
        cp = linked.current_period if linked else None
        self.summary_title.set_text(f"{tr(lang, 'current_period_card')} ({p_start} → {p_end})")
        self.summary_detail.set_text(
            tr(
                lang,
                'period_summary_fmt',
                total=f'{p_net / 3600.0:.2f}h',
                target=f'{target_h:.0f}h',
                counted=cp.counted_days if cp else 0,
            )
        )
        self.summary_progress.set_fraction(max(0.0, min(1.0, pct / 100.0)))
        self.summary_progress.show()

        if not periods:
            lbl = Gtk.Label(label=tr(lang, 'no_periods_data'))
            lbl.get_style_context().add_class('xattendo-hint')
            self.rows_box.pack_start(lbl, False, False, 20)
            return

        today_iso = campus_today().isoformat()
        row_idx = 0
        for period in periods:
            for d in sorted(period.days, key=lambda x: x.date, reverse=True):
                is_today = d.date == today_iso
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                rctx = row.get_style_context()
                rctx.add_class('xattendo-sched-row')
                if is_today:
                    rctx.add_class('xattendo-sched-row-today')
                elif row_idx % 2 == 1:
                    rctx.add_class('xattendo-sched-row-alt')
                row_idx += 1

                date_txt = f'★ {d.date}' if is_today else d.date
                hours_txt = format_compact_hours(d.hours * 3600.0)
                status_txt = tr(lang, 'status_counted' if d.counted else 'status_not_counted')
                values = [date_txt, period.label, hours_txt, status_txt]
                ltr_cells: List[Gtk.Widget] = []
                for col_idx, val in enumerate(values):
                    _, width, is_mono = PERIOD_COLUMNS[col_idx]
                    cell = Gtk.Label(label=val, xalign=0.5)
                    if is_mono:
                        ltr_cells.append(cell)
                    cell.set_size_request(width, -1)
                    cell.get_style_context().add_class(
                        'xattendo-sched-cell-mono' if is_mono else 'xattendo-sched-cell'
                    )
                    row.pack_start(cell, True, True, 0)
                apply_rtl_layout(row, is_rtl(lang), ltr_widgets=ltr_cells)
                self.rows_box.pack_start(row, False, False, 0)

    def _render_locks(self, lang: str) -> None:
        local = self._local
        locks = local.today_locks if local else []
        total_locked = local.today.locked_seconds if local else 0.0
        self.summary_title.set_text(f"{tr(lang, 'tab_locks').upper()} · {campus_today().isoformat()}")
        self.summary_detail.set_text(
            tr(lang, 'lock_summary_fmt', total=format_hm(total_locked), count=len(locks))
        )
        self.summary_progress.hide()

        if not locks:
            lbl = Gtk.Label(label=tr(lang, 'no_locks_day'))
            lbl.get_style_context().add_class('xattendo-hint')
            self.rows_box.pack_start(lbl, False, False, 20)
            return

        for idx, lp in enumerate(reversed(locks)):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            rctx = row.get_style_context()
            rctx.add_class('xattendo-sched-row')
            if idx % 2 == 1:
                rctx.add_class('xattendo-sched-row-alt')

            start_str = lp.start[11:19] if len(lp.start) >= 19 else lp.start
            end_str = '—' if lp.ongoing else (lp.end[11:19] if len(lp.end) >= 19 else lp.end)
            dur_str = format_hms(lp.seconds)
            status_str = tr(lang, 'status_ongoing' if lp.ongoing else 'status_completed')
            values = [start_str, end_str, dur_str, status_str]
            ltr_cells: List[Gtk.Widget] = []
            for col_idx, val in enumerate(values):
                _, width, is_mono = LOCK_COLUMNS[col_idx]
                cell = Gtk.Label(label=val, xalign=0.5)
                if is_mono:
                    ltr_cells.append(cell)
                cell.set_size_request(width, -1)
                cell.get_style_context().add_class(
                    'xattendo-sched-cell-mono' if is_mono else 'xattendo-sched-cell'
                )
                row.pack_start(cell, True, True, 0)
            apply_rtl_layout(row, is_rtl(lang), ltr_widgets=ltr_cells)
            self.rows_box.pack_start(row, False, False, 0)
