"""Embedded WebKit2 universal login window for 1337 Attendo and 42 Intra (any browser)."""

import os
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib, Gtk

try:
    gi.require_version('WebKit2', '4.0')
    from gi.repository import WebKit2
    WEBKIT_AVAILABLE = True
except (ImportError, ValueError):
    WebKit2 = None  # type: ignore
    WEBKIT_AVAILABLE = False

from xattendo_widget.constants import (
    ATTENDO_LOGIN_URL,
    ATTENDO_PROFILE_URL,
    DATA_DIR,
    INTRA_PROFILE_URL,
)
from xattendo_widget.i18n import is_rtl, normalize_lang, tr
from xattendo_widget.services.config_service import ConfigService
from xattendo_widget.ui.styles import apply_rtl_layout


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


class WebLoginWindow(Gtk.Window):
    """Built-in WebKit2 sign-in window that captures Attendo & 42 Intra cookies automatically."""

    def __init__(
        self,
        config_service: ConfigService,
        on_credentials_captured: Callable[[str, str], None],
        on_open_external: Callable[[str], None],
        on_visibility_changed: Optional[Callable[[bool], None]] = None,
    ) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.config_service = config_service
        self.on_credentials_captured = on_credentials_captured
        self.on_open_external = on_open_external
        self.on_visibility_changed = on_visibility_changed

        self._start_target: str = 'both'
        self._got_attendo: bool = False
        self._got_intra: bool = False
        self._navigated_to_intra: bool = False
        self._navigated_to_attendo: bool = False
        self._auto_close_id: Optional[int] = None
        self._cookie_manager = None
        self._web_view = None

        self.set_default_size(920, 680)
        self.set_resizable(True)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.get_style_context().add_class('xattendo-window')

        self.connect('delete-event', self._on_delete)
        self.connect('key-press-event', self._on_key_press)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        # Header bar
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bar.get_style_context().add_class('xattendo-login-bar')

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.attendo_pill = Gtk.Label()
        self.attendo_pill.get_style_context().add_class('xattendo-login-pill')
        self.intra_pill = Gtk.Label()
        self.intra_pill.get_style_context().add_class('xattendo-login-pill')
        top_row.pack_start(self.attendo_pill, False, False, 0)
        top_row.pack_start(self.intra_pill, False, False, 0)

        self.status_lbl = Gtk.Label(xalign=0)
        self.status_lbl.get_style_context().add_class('xattendo-hint')
        top_row.pack_start(self.status_lbl, True, True, 6)

        self.done_btn = Gtk.Button()
        self.done_btn.get_style_context().add_class('xattendo-btn-primary')
        self.done_btn.connect('clicked', lambda *_: self.close_window())
        top_row.pack_end(self.done_btn, False, False, 0)

        self.nav_intra_btn = Gtk.Button(label='42 Intra')
        self.nav_intra_btn.get_style_context().add_class('xattendo-btn')
        self.nav_intra_btn.connect('clicked', lambda *_: self._load_uri(INTRA_PROFILE_URL))
        top_row.pack_end(self.nav_intra_btn, False, False, 0)

        self.nav_attendo_btn = Gtk.Button(label='Attendo')
        self.nav_attendo_btn.get_style_context().add_class('xattendo-btn')
        self.nav_attendo_btn.connect('clicked', lambda *_: self._load_uri(ATTENDO_LOGIN_URL))
        top_row.pack_end(self.nav_attendo_btn, False, False, 0)

        bar.pack_start(top_row, False, False, 0)

        self.hint_lbl = Gtk.Label(xalign=0)
        self.hint_lbl.set_line_wrap(True)
        self.hint_lbl.get_style_context().add_class('xattendo-hint')
        bar.pack_start(self.hint_lbl, False, False, 0)

        root.pack_start(bar, False, False, 0)

        if WEBKIT_AVAILABLE:
            os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
            cookie_db = os.path.join(DATA_DIR, 'web_cookies.sqlite')
            ctx = WebKit2.WebContext.new()
            cm = ctx.get_cookie_manager()
            cm.set_persistent_storage(cookie_db, WebKit2.CookiePersistentStorage.SQLITE)
            if os.path.exists(cookie_db):
                try:
                    os.chmod(cookie_db, 0o600)
                except OSError:
                    pass
            self._cookie_manager = cm
            wv = WebKit2.WebView.new_with_context(ctx)
            wv.set_vexpand(True)
            wv.set_hexpand(True)
            wv.connect('load-changed', self._on_load_changed)
            self._web_view = wv
            root.pack_start(wv, True, True, 0)

        self.apply_language(self._lang())

    def _lang(self) -> str:
        return normalize_lang(self.config_service.config.language)

    def apply_language(self, lang: str) -> None:
        norm = normalize_lang(lang)
        apply_rtl_layout(
            self,
            is_rtl(norm),
            ltr_widgets=(self.nav_attendo_btn, self.nav_intra_btn),
        )
        self.set_title(tr(norm, 'web_login_title'))
        self.hint_lbl.set_text(tr(norm, 'web_login_banner'))
        self.done_btn.set_label(tr(norm, 'web_login_done_btn'))
        self._update_status_pills()

    def _update_status_pills(self) -> None:
        lang = self._lang()
        att_state = tr(lang, 'web_login_connected' if self._got_attendo else 'web_login_waiting')
        int_state = tr(lang, 'web_login_connected' if self._got_intra else 'web_login_waiting')
        self.attendo_pill.set_text(f'Attendo: {att_state}')
        self.intra_pill.set_text(f'42 Intra: {int_state}')

        for pill, ok in ((self.attendo_pill, self._got_attendo), (self.intra_pill, self._got_intra)):
            ctx = pill.get_style_context()
            if ok:
                ctx.add_class('linked')
            else:
                ctx.remove_class('linked')

        if self._got_attendo and self._got_intra:
            self.status_lbl.set_text(tr(lang, 'web_login_both_done'))
        elif self._got_attendo and self._navigated_to_intra:
            self.status_lbl.set_text(tr(lang, 'web_login_syncing_intra'))
        else:
            self.status_lbl.set_text('')

    def _load_uri(self, uri: str) -> None:
        if self._web_view is not None:
            self._web_view.load_uri(uri)

    def open_login(self, start_target: str = 'both') -> None:
        if not WEBKIT_AVAILABLE or self._web_view is None:
            self.on_open_external(INTRA_PROFILE_URL if start_target == 'intra' else ATTENDO_LOGIN_URL)
            return

        self._cancel_auto_close()
        self._start_target = start_target
        self._got_attendo = False
        self._got_intra = False
        self._navigated_to_intra = False
        self._navigated_to_attendo = False
        self.apply_language(self._lang())

        target_url = INTRA_PROFILE_URL if start_target == 'intra' else ATTENDO_LOGIN_URL
        self._load_uri(target_url)
        self.show_all()
        if self.on_visibility_changed:
            self.on_visibility_changed(True)
        self.present_with_time(Gtk.get_current_event_time() or Gdk.CURRENT_TIME)

    def _cancel_auto_close(self) -> None:
        if self._auto_close_id is not None:
            GLib.source_remove(self._auto_close_id)
            self._auto_close_id = None

    def close_window(self) -> bool:
        self._cancel_auto_close()
        self.hide()
        if self.on_visibility_changed:
            self.on_visibility_changed(False)
        return False

    def _on_delete(self, _widget, _event) -> bool:
        self.close_window()
        return True

    def _on_key_press(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.close_window()
            return True
        return False

    def _on_load_changed(self, web_view, load_event) -> None:
        if not WEBKIT_AVAILABLE or load_event != WebKit2.LoadEvent.FINISHED:
            return
        uri = web_view.get_uri() or ''
        self._inspect_cookies(uri)

    def _inspect_cookies(self, current_uri: str) -> None:
        if self._cookie_manager is None:
            return
        self._cookie_manager.get_cookies(
            ATTENDO_PROFILE_URL,
            None,
            lambda cm, res, uri=current_uri: self._on_attendo_cookies(cm, res, uri),
        )
        self._cookie_manager.get_cookies(
            'https://translate.intra.42.fr/',
            None,
            lambda cm, res, uri=current_uri: self._on_intra_cookies_translate(cm, res, uri),
        )

    def _on_attendo_cookies(self, cm, res, _uri: str) -> None:
        try:
            cookies = cm.get_cookies_finish(res) or []
        except Exception:
            return

        token = ''
        for c in cookies:
            if c.get_name() == 'student_token' and c.get_value():
                token = str(c.get_value()).strip()
                break

        if not token:
            return

        changed = not self._got_attendo or self.config_service.config.attendo_token != token
        self._got_attendo = True
        if changed:
            self.config_service.config.attendo_token = token
            self.config_service.save(notify=False)
            self.on_credentials_captured(token, '')

        if not self._got_intra and not self._navigated_to_intra:
            self._navigated_to_intra = True
            self._load_uri(INTRA_PROFILE_URL)

        self._update_status_pills()
        self._maybe_schedule_auto_close()

    def _on_intra_cookies_translate(self, cm, res, uri: str) -> None:
        pairs: List[Tuple[str, str]] = []
        try:
            for c in cm.get_cookies_finish(res) or []:
                pairs.append((c.get_name(), c.get_value()))
        except Exception:
            pass

        cm.get_cookies(
            INTRA_PROFILE_URL,
            None,
            lambda cm2, res2, u=uri, p=pairs: self._on_intra_cookies_profile(cm2, res2, u, p),
        )

    def _on_intra_cookies_profile(
        self,
        cm,
        res,
        uri: str,
        translate_pairs: List[Tuple[str, str]],
    ) -> None:
        pairs = list(translate_pairs)
        try:
            for c in cm.get_cookies_finish(res) or []:
                pairs.append((c.get_name(), c.get_value()))
        except Exception:
            pass

        # Only treat Intra as signed-in once past the login page and cookies exist
        on_intra_app = (
            uri.startswith('https://profile.intra.42.fr')
            and '/users/sign_in' not in uri
            and 'signin.intra.42.fr' not in uri
        )
        cookie_hdr = format_cookie_header(pairs)
        if not (on_intra_app and cookie_hdr):
            return

        changed = not self._got_intra or self.config_service.config.intra_cookie != cookie_hdr
        self._got_intra = True
        if changed:
            self.config_service.config.intra_cookie = cookie_hdr
            self.config_service.save(notify=False)
            self.on_credentials_captured('', cookie_hdr)

        if self._start_target == 'intra' and not self._got_attendo and not self._navigated_to_attendo:
            self._navigated_to_attendo = True
            self._load_uri(ATTENDO_LOGIN_URL)

        self._update_status_pills()
        self._maybe_schedule_auto_close()

    def _maybe_schedule_auto_close(self) -> None:
        if self._got_attendo and self._got_intra and self._auto_close_id is None:
            self._auto_close_id = GLib.timeout_add(900, self.close_window)
