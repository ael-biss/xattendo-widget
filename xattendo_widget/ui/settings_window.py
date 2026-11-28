"""Dedicated Settings window with explicit Save/Cancel and 42 Intra / Attendo linking."""

import time
from typing import Callable, Dict, Optional

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib, Gtk

from xattendo_widget import __version__
from xattendo_widget.constants import (
    ATTENDO_LOGIN_URL,
    DEFAULT_ALMOST_GOAL_MINUTES,
    DEFAULT_PERIOD_TARGET_HOURS,
    DEFAULT_REFRESH_INTERVAL,
    INTRA_PROFILE_URL,
)
from xattendo_widget.i18n import is_rtl, normalize_lang, tr
from xattendo_widget.models import LinkedAccountsState, VALID_BROWSERS, VALID_PILL_MODES
from xattendo_widget.services.config_service import ConfigService
from xattendo_widget.services.update_service import UpdateService
from xattendo_widget.ui.styles import apply_rtl_layout, load_state_icon


class SettingsWindow(Gtk.Window):
    def __init__(
        self,
        config_service: ConfigService,
        update_service: UpdateService,
        on_reset_position: Callable[[], None],
        on_sync_accounts: Callable[[], None],
        on_open_url: Callable[[str], None],
        on_top_bar_mode_changed: Optional[Callable[[bool], None]] = None,
        on_top_bar_preset: Optional[Callable[[str], None]] = None,
        on_reload_app: Optional[Callable[[], None]] = None,
        on_quit_app: Optional[Callable[[], None]] = None,
        on_open_web_login: Optional[Callable[[str], None]] = None,
        is_child_modal_open: Optional[Callable[[], bool]] = None,
    ) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.config_service = config_service
        self.update_service = update_service
        self.on_reset_position = on_reset_position
        self.on_sync_accounts = on_sync_accounts
        self.on_open_url = on_open_url
        self.on_top_bar_mode_changed = on_top_bar_mode_changed
        self.on_top_bar_preset = on_top_bar_preset
        self.on_reload_app = on_reload_app
        self.on_quit_app = on_quit_app
        self.on_open_web_login = on_open_web_login
        self._is_child_modal_open = is_child_modal_open

        self._lang_buttons: Dict[str, Gtk.Button] = {}
        self._preset_buttons: Dict[str, Gtk.Button] = {}
        self._mode_buttons: Dict[str, Gtk.Button] = {}
        self._browser_buttons: Dict[str, Gtk.Button] = {}
        self._draft_mode: str = 'hms'
        self._draft_browser: str = 'auto'
        self._linked_state: Optional[LinkedAccountsState] = None
        self._pending_update_url: str = ''
        self._pending_update_ver: str = ''
        self._opened_at: float = 0.0

        self.set_default_size(490, 680)
        self.set_resizable(True)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.get_style_context().add_class('xattendo-window')

        self.connect('delete-event', self._on_delete)
        self.connect('key-press-event', self._on_key_press)
        self.connect('focus-out-event', self._on_focus_out)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(outer)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        outer.pack_start(scrolled, True, True, 0)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.set_border_width(18)
        scrolled.add(root)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        pixbuf = load_state_icon(24, 'normal')
        if pixbuf:
            header.pack_start(Gtk.Image.new_from_pixbuf(pixbuf), False, False, 0)
        title_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.header_title_lbl = Gtk.Label(xalign=0)
        self.header_title_lbl.get_style_context().add_class('xattendo-title')
        self.header_sub_lbl = Gtk.Label(xalign=0)
        self.header_sub_lbl.get_style_context().add_class('xattendo-subtitle')
        title_col.pack_start(self.header_title_lbl, False, False, 0)
        title_col.pack_start(self.header_sub_lbl, False, False, 0)
        header.pack_start(title_col, True, True, 0)
        root.pack_start(header, False, False, 0)

        root.pack_start(self._build_language_section(), False, False, 0)
        root.pack_start(self._build_display_section(), False, False, 0)
        root.pack_start(self._build_accounts_section(), False, False, 0)
        root.pack_start(self._build_notifications_section(), False, False, 0)
        root.pack_start(self._build_tools_section(), False, False, 0)

        # Sticky Footer: Cancel / Save
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        footer.set_border_width(14)

        self.cancel_btn = Gtk.Button()
        self.cancel_btn.get_style_context().add_class('xattendo-btn')
        self.cancel_btn.connect('clicked', lambda *_: self.close_window())

        self.save_btn = Gtk.Button()
        self.save_btn.get_style_context().add_class('xattendo-btn-primary')
        self.save_btn.connect('clicked', self._on_save_clicked)

        footer.pack_end(self.save_btn, False, False, 0)
        footer.pack_end(self.cancel_btn, False, False, 0)
        outer.pack_end(footer, False, False, 0)

        self._sync_from_config()

    def _lang(self) -> str:
        return normalize_lang(self.config_service.config.language)

    def _build_language_section(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.get_style_context().add_class('xattendo-section')

        self.lang_sec_title = Gtk.Label(xalign=0)
        self.lang_sec_title.get_style_context().add_class('xattendo-section-title')
        box.pack_start(self.lang_sec_title, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.lang_field_lbl = Gtk.Label(xalign=0)
        self.lang_field_lbl.get_style_context().add_class('xattendo-field-label')
        row.pack_start(self.lang_field_lbl, True, True, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_homogeneous(True)
        for code, title in (('en', 'English'), ('fr', 'Français'), ('ar', 'العربية')):
            btn = Gtk.Button(label=title)
            btn.connect('clicked', lambda _b, c=code: self._on_language_selected(c))
            btn_box.pack_start(btn, True, True, 0)
            self._lang_buttons[code] = btn
        row.pack_end(btn_box, False, False, 0)
        box.pack_start(row, False, False, 0)
        return box

    def _on_language_selected(self, lang: str) -> None:
        norm = normalize_lang(lang)
        if self.config_service.config.language == norm:
            return
        self.config_service.config.language = norm
        self.config_service.save(notify=True)
        self.apply_language(norm)

    def _update_language_buttons(self, lang: str) -> None:
        norm = normalize_lang(lang)
        for code, btn in self._lang_buttons.items():
            ctx = btn.get_style_context()
            ctx.remove_class('xattendo-btn')
            ctx.remove_class('xattendo-btn-primary')
            ctx.add_class('xattendo-btn-primary' if code == norm else 'xattendo-btn')

    def _build_display_section(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.get_style_context().add_class('xattendo-section')

        self.topbar_sec_title = Gtk.Label(xalign=0)
        self.topbar_sec_title.get_style_context().add_class('xattendo-section-title')
        box.pack_start(self.topbar_sec_title, False, False, 0)

        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.topbar_mode_lbl = Gtk.Label(xalign=0)
        self.topbar_mode_lbl.get_style_context().add_class('xattendo-field-label')
        self.top_bar_switch = Gtk.Switch()
        self.top_bar_switch.connect('notify::active', lambda sw, *_: self.preset_row.set_sensitive(sw.get_active()))
        mode_row.pack_start(self.topbar_mode_lbl, True, True, 0)
        mode_row.pack_end(self.top_bar_switch, False, False, 0)
        box.pack_start(mode_row, False, False, 0)

        pin_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.pin_pos_lbl = Gtk.Label(xalign=0)
        self.pin_pos_lbl.get_style_context().add_class('xattendo-field-label')
        self.pin_switch = Gtk.Switch()
        pin_row.pack_start(self.pin_pos_lbl, True, True, 0)
        pin_row.pack_end(self.pin_switch, False, False, 0)
        box.pack_start(pin_row, False, False, 0)

        eta_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.show_pill_eta_lbl = Gtk.Label(xalign=0)
        self.show_pill_eta_lbl.get_style_context().add_class('xattendo-field-label')
        self.show_pill_eta_switch = Gtk.Switch()
        eta_row.pack_start(self.show_pill_eta_lbl, True, True, 0)
        eta_row.pack_end(self.show_pill_eta_switch, False, False, 0)
        box.pack_start(eta_row, False, False, 0)

        self.topbar_hint_lbl = Gtk.Label(xalign=0)
        self.topbar_hint_lbl.set_line_wrap(True)
        self.topbar_hint_lbl.set_max_width_chars(46)
        self.topbar_hint_lbl.get_style_context().add_class('xattendo-hint')
        box.pack_start(self.topbar_hint_lbl, False, False, 0)

        self.preset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.preset_row.set_homogeneous(True)
        for preset in ('left', 'center_right', 'right'):
            btn = Gtk.Button()
            btn.get_style_context().add_class('xattendo-btn')
            btn.connect('clicked', lambda _b, p=preset: self._on_preset_clicked(p))
            self.preset_row.pack_start(btn, True, True, 0)
            self._preset_buttons[preset] = btn
        box.pack_start(self.preset_row, False, False, 0)

        self.pill_mode_lbl = Gtk.Label(xalign=0)
        self.pill_mode_lbl.get_style_context().add_class('xattendo-hint')
        box.pack_start(self.pill_mode_lbl, False, False, 2)

        self.pill_mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pill_mode_row.set_homogeneous(True)
        for mode in VALID_PILL_MODES:
            btn = Gtk.Button()
            btn.connect('clicked', lambda _b, m=mode: self._select_pill_mode(m))
            self.pill_mode_row.pack_start(btn, True, True, 0)
            self._mode_buttons[mode] = btn
        box.pack_start(self.pill_mode_row, False, False, 0)

        return box

    def _select_pill_mode(self, mode: str) -> None:
        self._draft_mode = mode
        for m, btn in self._mode_buttons.items():
            ctx = btn.get_style_context()
            ctx.remove_class('xattendo-btn')
            ctx.remove_class('xattendo-btn-primary')
            ctx.add_class('xattendo-btn-primary' if m == mode else 'xattendo-btn')

    def _on_preset_clicked(self, preset: str) -> None:
        if self.on_top_bar_preset:
            self.on_top_bar_preset(preset)

    def _build_accounts_section(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.get_style_context().add_class('xattendo-section')

        self.acc_sec_title = Gtk.Label(xalign=0)
        self.acc_sec_title.get_style_context().add_class('xattendo-section-title')
        box.pack_start(self.acc_sec_title, False, False, 0)

        # Live link status row
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.acc_status_lbl = Gtk.Label(xalign=0)
        self.acc_status_lbl.get_style_context().add_class('xattendo-hint')
        self.sync_now_btn = Gtk.Button()
        self.sync_now_btn.get_style_context().add_class('xattendo-btn-primary')
        self.sync_now_btn.connect('clicked', lambda *_: self.on_sync_accounts())
        status_row.pack_start(self.acc_status_lbl, True, True, 0)
        status_row.pack_end(self.sync_now_btn, False, False, 0)
        box.pack_start(status_row, False, False, 0)

        # Universal One-Click Login (works with any browser)
        self.web_login_btn = Gtk.Button()
        self.web_login_btn.get_style_context().add_class('xattendo-btn-primary')
        self.web_login_btn.connect('clicked', self._on_web_login_clicked)
        box.pack_start(self.web_login_btn, False, False, 0)

        self.web_login_hint_lbl = Gtk.Label(xalign=0)
        self.web_login_hint_lbl.set_line_wrap(True)
        self.web_login_hint_lbl.set_max_width_chars(46)
        self.web_login_hint_lbl.get_style_context().add_class('xattendo-hint')
        box.pack_start(self.web_login_hint_lbl, False, False, 0)

        # Browser quick-open links
        link_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        link_row.set_homogeneous(True)
        self.open_intra_btn = Gtk.Button()
        self.open_intra_btn.get_style_context().add_class('xattendo-btn')
        self.open_intra_btn.connect('clicked', lambda *_: self.on_open_url(INTRA_PROFILE_URL))
        self.open_attendo_btn = Gtk.Button()
        self.open_attendo_btn.get_style_context().add_class('xattendo-btn')
        self.open_attendo_btn.connect('clicked', lambda *_: self.on_open_url(ATTENDO_LOGIN_URL))
        link_row.pack_start(self.open_intra_btn, True, True, 0)
        link_row.pack_start(self.open_attendo_btn, True, True, 0)
        box.pack_start(link_row, False, False, 0)

        self.browser_lbl = Gtk.Label(xalign=0)
        self.browser_lbl.get_style_context().add_class('xattendo-hint')
        box.pack_start(self.browser_lbl, False, False, 0)

        self.browser_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.browser_row.set_homogeneous(True)
        for b in VALID_BROWSERS:
            btn = Gtk.Button()
            btn.connect('clicked', lambda _b, br=b: self._select_browser(br))
            self.browser_row.pack_start(btn, True, True, 0)
            self._browser_buttons[b] = btn
        box.pack_start(self.browser_row, False, False, 0)

        self.intra_login_lbl = Gtk.Label(xalign=0)
        self.intra_login_lbl.get_style_context().add_class('xattendo-hint')
        box.pack_start(self.intra_login_lbl, False, False, 0)
        self.intra_login_entry = Gtk.Entry()
        self.intra_login_entry.set_direction(Gtk.TextDirection.LTR)
        box.pack_start(self.intra_login_entry, False, False, 0)

        self.attendo_token_lbl = Gtk.Label(xalign=0)
        self.attendo_token_lbl.get_style_context().add_class('xattendo-hint')
        box.pack_start(self.attendo_token_lbl, False, False, 0)
        self.attendo_token_entry = Gtk.Entry()
        self.attendo_token_entry.set_visibility(False)
        self.attendo_token_entry.set_direction(Gtk.TextDirection.LTR)
        box.pack_start(self.attendo_token_entry, False, False, 0)

        # Period target & sync interval
        target_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.period_target_lbl = Gtk.Label(xalign=0)
        self.period_target_lbl.get_style_context().add_class('xattendo-field-label')
        t_adj = Gtk.Adjustment(value=DEFAULT_PERIOD_TARGET_HOURS, lower=1, upper=200, step_increment=1, page_increment=5)
        self.period_target_spin = Gtk.SpinButton(adjustment=t_adj, numeric=True)
        self.period_target_spin.set_width_chars(3)
        self.hours_unit_lbl = Gtk.Label(xalign=0)
        self.hours_unit_lbl.get_style_context().add_class('xattendo-hint')
        target_row.pack_start(self.period_target_lbl, True, True, 0)
        target_row.pack_end(self.hours_unit_lbl, False, False, 2)
        target_row.pack_end(self.period_target_spin, False, False, 4)
        box.pack_start(target_row, False, False, 0)

        int_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.refresh_int_lbl = Gtk.Label(xalign=0)
        self.refresh_int_lbl.get_style_context().add_class('xattendo-field-label')
        adj = Gtk.Adjustment(value=DEFAULT_REFRESH_INTERVAL, lower=30, upper=600, step_increment=15, page_increment=30)
        self.refresh_spin = Gtk.SpinButton(adjustment=adj, numeric=True)
        self.refresh_spin.set_width_chars(3)
        self.sec_unit_lbl = Gtk.Label(xalign=0)
        self.sec_unit_lbl.get_style_context().add_class('xattendo-hint')
        int_row.pack_start(self.refresh_int_lbl, True, True, 0)
        int_row.pack_end(self.sec_unit_lbl, False, False, 2)
        int_row.pack_end(self.refresh_spin, False, False, 4)
        box.pack_start(int_row, False, False, 0)

        return box

    def _select_browser(self, browser: str) -> None:
        self._draft_browser = browser
        for b, btn in self._browser_buttons.items():
            ctx = btn.get_style_context()
            ctx.remove_class('xattendo-btn')
            ctx.remove_class('xattendo-btn-primary')
            ctx.add_class('xattendo-btn-primary' if b == browser else 'xattendo-btn')

    def _build_notifications_section(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.get_style_context().add_class('xattendo-section')

        self.notif_sec_title = Gtk.Label(xalign=0)
        self.notif_sec_title.get_style_context().add_class('xattendo-section-title')
        box.pack_start(self.notif_sec_title, False, False, 0)

        notif_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.notif_lbl = Gtk.Label(xalign=0)
        self.notif_lbl.get_style_context().add_class('xattendo-field-label')
        self.notif_switch = Gtk.Switch()
        notif_row.pack_start(self.notif_lbl, True, True, 0)
        notif_row.pack_end(self.notif_switch, False, False, 0)
        box.pack_start(notif_row, False, False, 0)

        goal_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.goal_notify_lbl = Gtk.Label(xalign=0)
        self.goal_notify_lbl.get_style_context().add_class('xattendo-field-label')
        self.goal_notify_switch = Gtk.Switch()
        goal_row.pack_start(self.goal_notify_lbl, True, True, 0)
        goal_row.pack_end(self.goal_notify_switch, False, False, 0)
        box.pack_start(goal_row, False, False, 0)

        almost_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.almost_lbl = Gtk.Label(xalign=0)
        self.almost_lbl.get_style_context().add_class('xattendo-field-label')
        self.almost_switch = Gtk.Switch()
        self.almost_switch.connect('notify::active', lambda sw, *_: self.almost_spin.set_sensitive(sw.get_active()))
        almost_row.pack_start(self.almost_lbl, True, True, 0)
        almost_row.pack_end(self.almost_switch, False, False, 0)
        box.pack_start(almost_row, False, False, 0)

        min_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.almost_min_lbl = Gtk.Label(xalign=0)
        self.almost_min_lbl.get_style_context().add_class('xattendo-hint')
        adj = Gtk.Adjustment(value=DEFAULT_ALMOST_GOAL_MINUTES, lower=5, upper=120, step_increment=5, page_increment=15)
        self.almost_spin = Gtk.SpinButton(adjustment=adj, numeric=True)
        self.almost_spin.set_width_chars(3)
        self.min_unit_lbl = Gtk.Label(xalign=0)
        self.min_unit_lbl.get_style_context().add_class('xattendo-hint')
        min_row.pack_start(self.almost_min_lbl, True, True, 0)
        min_row.pack_end(self.min_unit_lbl, False, False, 2)
        min_row.pack_end(self.almost_spin, False, False, 4)
        box.pack_start(min_row, False, False, 0)

        return box

    def _build_tools_section(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_homogeneous(True)
        self.refresh_data_btn = Gtk.Button()
        self.refresh_data_btn.get_style_context().add_class('xattendo-btn')
        self.refresh_data_btn.connect('clicked', lambda *_: self.on_sync_accounts())

        self.reset_pos_btn = Gtk.Button()
        self.reset_pos_btn.get_style_context().add_class('xattendo-btn')
        self.reset_pos_btn.connect('clicked', lambda *_: self.on_reset_position())
        row.pack_start(self.refresh_data_btn, True, True, 0)
        row.pack_start(self.reset_pos_btn, True, True, 0)
        outer.pack_start(row, False, False, 0)

        app_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        app_row.set_homogeneous(True)
        self.reload_app_btn = Gtk.Button()
        self.reload_app_btn.get_style_context().add_class('xattendo-btn')
        self.reload_app_btn.connect('clicked', self._on_reload_clicked)

        self.quit_app_btn = Gtk.Button()
        self.quit_app_btn.get_style_context().add_class('xattendo-btn')
        self.quit_app_btn.get_style_context().add_class('xattendo-btn-danger')
        self.quit_app_btn.connect('clicked', self._on_quit_clicked)

        app_row.pack_start(self.reload_app_btn, True, True, 0)
        app_row.pack_start(self.quit_app_btn, True, True, 0)
        outer.pack_start(app_row, False, False, 0)

        upd_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        upd_box.get_style_context().add_class('xattendo-section')
        self.update_status_lbl = Gtk.Label(xalign=0)
        self.update_status_lbl.get_style_context().add_class('xattendo-hint')
        self.update_btn = Gtk.Button()
        self.update_btn.get_style_context().add_class('xattendo-btn')
        self.update_btn.connect('clicked', self._on_update_clicked)
        upd_box.pack_start(self.update_status_lbl, True, True, 0)
        upd_box.pack_end(self.update_btn, False, False, 0)
        outer.pack_start(upd_box, False, False, 0)

        return outer

    def _on_reload_clicked(self, _btn: Gtk.Button) -> None:
        self.hide()
        if self.on_reload_app:
            self.on_reload_app()

    def _on_quit_clicked(self, _btn: Gtk.Button) -> None:
        self.hide()
        if self.on_quit_app:
            self.on_quit_app()
        else:
            Gtk.main_quit()

    def update_linked_status(self, linked: Optional[LinkedAccountsState]) -> None:
        self._linked_state = linked
        lang = self._lang()
        if linked is None:
            self.acc_status_lbl.set_text('Intra: —  •  Attendo: —')
            return
        intra_txt = tr(lang, 'linked_badge' if linked.intra_linked else 'not_linked_badge')
        att_txt = tr(lang, 'linked_badge' if linked.attendo_linked else 'not_linked_badge')
        self.acc_status_lbl.set_text(f'42 Intra: {intra_txt}  •  Attendo: {att_txt}')

    def apply_language(self, lang: str) -> None:
        norm = normalize_lang(lang)
        ltr_keep = [
            self.preset_row,
            self.pill_mode_row,
            self.browser_row,
            self.intra_login_entry,
            self.attendo_token_entry,
            self.period_target_spin,
            self.refresh_spin,
            self.almost_spin,
        ]
        apply_rtl_layout(self, is_rtl(norm), ltr_widgets=ltr_keep)

        self.set_title(tr(norm, 'settings_win_title'))
        self.header_title_lbl.set_text(tr(norm, 'widget_settings'))
        self.header_sub_lbl.set_text(tr(norm, 'settings_subtitle'))

        self.lang_sec_title.set_text(tr(norm, 'sec_language'))
        self.lang_field_lbl.set_text(tr(norm, 'language_label'))
        self._update_language_buttons(norm)

        self.topbar_sec_title.set_text(tr(norm, 'sec_top_bar'))
        self.topbar_mode_lbl.set_text(tr(norm, 'dock_top_bar'))
        self.pin_pos_lbl.set_text(tr(norm, 'pin_position_toggle'))
        self.show_pill_eta_lbl.set_text(tr(norm, 'show_pill_eta_toggle'))
        self.topbar_hint_lbl.set_text(tr(norm, 'top_bar_hint'))
        self._preset_buttons['left'].set_label(tr(norm, 'preset_left'))
        self._preset_buttons['center_right'].set_label(tr(norm, 'preset_center_right'))
        self._preset_buttons['right'].set_label(tr(norm, 'preset_right'))

        self.pill_mode_lbl.set_text(tr(norm, 'pill_display_mode_label'))
        self._mode_buttons['hms'].set_label(tr(norm, 'mode_hms'))
        self._mode_buttons['hours'].set_label(tr(norm, 'mode_hours'))
        self._mode_buttons['period_pct'].set_label(tr(norm, 'mode_period_pct'))

        self.acc_sec_title.set_text(tr(norm, 'sec_accounts'))
        self.sync_now_btn.set_label(tr(norm, 'sync_now_btn'))
        self.web_login_btn.set_label(tr(norm, 'web_login_btn'))
        self.web_login_hint_lbl.set_text(tr(norm, 'web_login_hint'))
        self.open_intra_btn.set_label(tr(norm, 'open_intra_btn'))
        self.open_attendo_btn.set_label(tr(norm, 'open_attendo_btn'))
        self.browser_lbl.set_text(tr(norm, 'browser_pref_label'))
        for b in VALID_BROWSERS:
            self._browser_buttons[b].set_label(tr(norm, f'browser_{b}'))
        self.intra_login_lbl.set_text(tr(norm, 'intra_login_label'))
        self.intra_login_entry.set_placeholder_text(tr(norm, 'intra_login_placeholder'))
        self.attendo_token_lbl.set_text(tr(norm, 'attendo_token_label'))
        self.attendo_token_entry.set_placeholder_text(tr(norm, 'attendo_token_placeholder'))
        self.period_target_lbl.set_text(tr(norm, 'period_target_label'))
        self.hours_unit_lbl.set_text(tr(norm, 'hours_short'))
        self.refresh_int_lbl.set_text(tr(norm, 'refresh_interval_label'))
        self.sec_unit_lbl.set_text(tr(norm, 'sec_short'))
        self.update_linked_status(self._linked_state)

        self.notif_sec_title.set_text(tr(norm, 'sec_notifications'))
        self.notif_lbl.set_text(tr(norm, 'desktop_notifications'))
        self.goal_notify_lbl.set_text(tr(norm, 'goal_reached_notify'))
        self.almost_lbl.set_text(tr(norm, 'almost_goal_toggle'))
        self.almost_min_lbl.set_text(tr(norm, 'minutes_before_goal'))
        self.min_unit_lbl.set_text(tr(norm, 'min_short'))

        self.refresh_data_btn.set_label(tr(norm, 'refresh_data_btn'))
        self.reset_pos_btn.set_label(tr(norm, 'reset_position'))
        self.reload_app_btn.set_label(tr(norm, 'reload_app'))
        self.quit_app_btn.set_label(tr(norm, 'quit_app'))

        if self._pending_update_ver:
            self.update_status_lbl.set_text(tr(norm, 'update_available_lbl', version=self._pending_update_ver))
            self.update_btn.set_label(tr(norm, 'install_version', version=self._pending_update_ver))
        else:
            self.update_status_lbl.set_text(tr(norm, 'version_label', version=__version__))
            self.update_btn.set_label(tr(norm, 'check_updates'))

        self.cancel_btn.set_label(tr(norm, 'cancel'))
        self.save_btn.set_label(tr(norm, 'save'))

    def _on_update_clicked(self, _btn: Gtk.Button) -> None:
        lang = self._lang()
        if self._pending_update_url:
            self.update_btn.set_sensitive(False)
            self.update_status_lbl.set_text(tr(lang, 'downloading_update'))
            self.update_service.download_and_apply_async(
                self._pending_update_url,
                lambda ok, msg: GLib.idle_add(self._on_update_applied, ok, msg),
            )
            return

        self.update_btn.set_sensitive(False)
        self.update_status_lbl.set_text(tr(lang, 'checking_updates'))
        self.update_service.check_async(
            lambda ver, url, err: GLib.idle_add(self._on_update_checked, ver, url, err)
        )

    def _on_update_checked(self, version, url, error) -> bool:
        lang = self._lang()
        self.update_btn.set_sensitive(True)
        if error:
            self.update_status_lbl.set_text(f'v{__version__} • {error}')
        elif version and url:
            self._pending_update_url = url
            self._pending_update_ver = version
            self.update_status_lbl.set_text(tr(lang, 'update_available_lbl', version=version))
            self.update_btn.set_label(tr(lang, 'install_version', version=version))
            self.update_btn.get_style_context().add_class('xattendo-btn-primary')
        else:
            self.update_status_lbl.set_text(tr(lang, 'up_to_date', version=__version__))
        return False

    def _on_update_applied(self, ok: bool, msg: str) -> bool:
        lang = self._lang()
        if ok:
            self.update_status_lbl.set_text(tr(lang, 'updated_restarting'))
            GLib.timeout_add(400, self.update_service.restart_installed)
        else:
            self.update_btn.set_sensitive(True)
            self.update_status_lbl.set_text(tr(lang, 'update_failed', msg=msg))
        return False

    def _sync_from_config(self) -> None:
        cfg = self.config_service.config
        self.top_bar_switch.set_active(cfg.top_bar_mode)
        self.pin_switch.set_active(cfg.position_locked)
        self.show_pill_eta_switch.set_active(cfg.show_pill_eta)
        self.preset_row.set_sensitive(cfg.top_bar_mode)
        self._select_pill_mode(cfg.pill_display_mode)
        self._select_browser(cfg.browser_preference)
        self.intra_login_entry.set_text(cfg.intra_login or '')
        self.attendo_token_entry.set_text(cfg.attendo_token or '')
        self.period_target_spin.set_value(cfg.period_target_hours)
        self.refresh_spin.set_value(cfg.refresh_interval_seconds)
        self.notif_switch.set_active(cfg.notifications_enabled)
        self.goal_notify_switch.set_active(cfg.goal_reached_notify)
        self.almost_switch.set_active(cfg.almost_goal_enabled)
        self.almost_spin.set_value(cfg.almost_goal_minutes)
        self.almost_spin.set_sensitive(cfg.almost_goal_enabled)
        self.apply_language(cfg.language)

    def _on_save_clicked(self, _btn: Gtk.Button) -> None:
        cfg = self.config_service.config
        prev_top_bar_mode = cfg.top_bar_mode

        cfg.top_bar_mode = self.top_bar_switch.get_active()
        cfg.position_locked = self.pin_switch.get_active()
        cfg.show_pill_eta = self.show_pill_eta_switch.get_active()
        cfg.pill_display_mode = self._draft_mode
        cfg.browser_preference = self._draft_browser
        cfg.intra_login = self.intra_login_entry.get_text().strip()
        cfg.attendo_token = self.attendo_token_entry.get_text().strip()
        cfg.period_target_hours = float(self.period_target_spin.get_value())
        cfg.refresh_interval_seconds = int(self.refresh_spin.get_value())
        cfg.notifications_enabled = self.notif_switch.get_active()
        cfg.goal_reached_notify = self.goal_notify_switch.get_active()
        cfg.almost_goal_enabled = self.almost_switch.get_active()
        cfg.almost_goal_minutes = int(self.almost_spin.get_value())

        self.hide()
        if cfg.top_bar_mode != prev_top_bar_mode and self.on_top_bar_mode_changed:
            self.config_service.save(notify=False)
            GLib.idle_add(self.on_top_bar_mode_changed, cfg.top_bar_mode)
        else:
            self.config_service.save(notify=True)
            self.on_sync_accounts()

    def _on_web_login_clicked(self, _btn: Gtk.Button) -> None:
        if self.on_open_web_login is not None:
            self.on_open_web_login('both')
        else:
            self.on_open_url(ATTENDO_LOGIN_URL)

    def sync_captured_credentials(self) -> None:
        if self.get_visible():
            self.attendo_token_entry.set_text(self.config_service.config.attendo_token or '')

    @property
    def is_modal_open(self) -> bool:
        return bool(self._is_child_modal_open()) if self._is_child_modal_open else False

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

    def _on_focus_out(self, _widget, _event) -> bool:
        if not self.get_visible() or self.is_modal_open or (time.monotonic() - self._opened_at) < 0.20:
            return False
        display = Gdk.Display.get_default()
        if display is not None:
            seat = display.get_default_seat()
            pointer = seat.get_pointer() if seat is not None else None
            if pointer is not None:
                _screen, px, py = pointer.get_position()
                if self.contains_screen_point(px, py):
                    return False
        self.close_window()
        return False

    def _on_key_press(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.close_window()
            return True
        return False

    def _on_delete(self, _widget, _event) -> bool:
        self.close_window()
        return True

    def close_window(self) -> None:
        self.hide()

    def open_window(self, linked: Optional[LinkedAccountsState] = None) -> None:
        if linked is not None:
            self._linked_state = linked
        self._opened_at = time.monotonic()
        self._sync_from_config()
        self.show_all()
        self.present_with_time(Gtk.get_current_event_time() or Gdk.CURRENT_TIME)
