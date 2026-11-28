"""Interactive first-time Onboarding & Quick Guide window."""

import datetime
from typing import Callable, Dict, List, Optional

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gtk

from xattendo_widget.core.calculator import campus_now, campus_zone
from xattendo_widget.i18n import is_rtl, normalize_lang, tr
from xattendo_widget.services.config_service import ConfigService
from xattendo_widget.ui.ring_widget import CountedDaysBar, DayTimeline, ProgressRing
from xattendo_widget.ui.styles import apply_rtl_layout, load_state_icon


class OnboardingWindow(Gtk.Window):
    """4-step visual walkthrough shown on first launch and reopenable from Settings."""

    TOTAL_STEPS = 4

    def __init__(
        self,
        config_service: ConfigService,
        on_open_web_login: Callable[[str], None],
        on_finished: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.config_service = config_service
        self.on_open_web_login = on_open_web_login
        self.on_finished = on_finished

        self._step: int = 0
        self._lang_buttons: Dict[str, Gtk.Button] = {}
        self._step_dots: List[Gtk.Box] = []
        self._slide_titles: List[Gtk.Label] = []
        self._slide_subs: List[Gtk.Label] = []
        self._slide_bullets: List[List[Gtk.Label]] = []
        self._ltr_widgets: List[Gtk.Widget] = []

        self.set_default_size(520, 530)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.get_style_context().add_class('xattendo-window')

        self.connect('delete-event', self._on_delete)
        self.connect('key-press-event', self._on_key_press)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_border_width(18)
        self.add(root)

        # Header: Icon + Title + Step Counter + EN|FR|AR switcher
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        pixbuf = load_state_icon(24, 'normal')
        if pixbuf:
            header.pack_start(Gtk.Image.new_from_pixbuf(pixbuf), False, False, 0)
        else:
            badge_42 = Gtk.Label(label='42')
            badge_42.get_style_context().add_class('xattendo-badge-42')
            header.pack_start(badge_42, False, False, 0)

        title_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.header_title_lbl = Gtk.Label(xalign=0)
        self.header_title_lbl.get_style_context().add_class('xattendo-title')
        self.step_counter_lbl = Gtk.Label(xalign=0)
        self.step_counter_lbl.get_style_context().add_class('xattendo-subtitle')
        title_col.pack_start(self.header_title_lbl, False, False, 0)
        title_col.pack_start(self.step_counter_lbl, False, False, 0)
        header.pack_start(title_col, True, True, 0)

        self.lang_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for code, short in (('en', 'EN'), ('fr', 'FR'), ('ar', 'AR')):
            btn = Gtk.Button(label=short)
            btn.connect('clicked', lambda _b, c=code: self._on_language_selected(c))
            self.lang_row.pack_start(btn, False, False, 0)
            self._lang_buttons[code] = btn
        self._ltr_widgets.append(self.lang_row)
        header.pack_end(self.lang_row, False, False, 0)
        root.pack_start(header, False, False, 0)

        # Content Stack (4 slides)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(180)
        self.stack.set_vhomogeneous(True)
        self.stack.add_named(self._build_slide_0(), 'step-0')
        self.stack.add_named(self._build_slide_1(), 'step-1')
        self.stack.add_named(self._build_slide_2(), 'step-2')
        self.stack.add_named(self._build_slide_3(), 'step-3')
        root.pack_start(self.stack, True, True, 0)

        # Footer: Skip/Back  ---  Step Dots  ---  Next/Get Started
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.back_btn = Gtk.Button()
        self.back_btn.get_style_context().add_class('xattendo-btn')
        self.back_btn.connect('clicked', lambda *_: self._go_back())
        footer.pack_start(self.back_btn, False, False, 0)

        dots_wrap = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        dots_wrap.set_valign(Gtk.Align.CENTER)
        dots_wrap.set_halign(Gtk.Align.CENTER)
        for _ in range(self.TOTAL_STEPS):
            dot = Gtk.Box()
            dot.get_style_context().add_class('xattendo-step-dot')
            dots_wrap.pack_start(dot, False, False, 0)
            self._step_dots.append(dot)
        footer.pack_start(dots_wrap, True, True, 0)

        self.next_btn = Gtk.Button()
        self.next_btn.get_style_context().add_class('xattendo-btn-primary')
        self.next_btn.connect('clicked', lambda *_: self._go_next())
        footer.pack_end(self.next_btn, False, False, 0)
        root.pack_end(footer, False, False, 0)

        self.apply_language(self._lang())
        self._update_step_ui()

    @property
    def current_step(self) -> int:
        return self._step

    def _lang(self) -> str:
        return normalize_lang(self.config_service.config.language)

    def _build_slide_shell(self, preview_widget: Gtk.Widget, bullet_count: int) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.get_style_context().add_class('xattendo-guide-card')

        title_lbl = Gtk.Label(xalign=0)
        title_lbl.get_style_context().add_class('xattendo-guide-heading')
        sub_lbl = Gtk.Label(xalign=0)
        sub_lbl.set_line_wrap(True)
        sub_lbl.set_max_width_chars(56)
        sub_lbl.get_style_context().add_class('xattendo-hint')
        card.pack_start(title_lbl, False, False, 0)
        card.pack_start(sub_lbl, False, False, 0)

        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preview_box.get_style_context().add_class('xattendo-guide-preview')
        preview_box.pack_start(preview_widget, False, False, 0)
        card.pack_start(preview_box, False, False, 0)

        bullets_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        bullet_labels: List[Gtk.Label] = []
        for _ in range(bullet_count):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            dot = Gtk.Label(label='•')
            dot.set_valign(Gtk.Align.START)
            dot.get_style_context().add_class('xattendo-guide-bullet-dot')
            lbl = Gtk.Label(xalign=0)
            lbl.set_line_wrap(True)
            lbl.set_max_width_chars(54)
            lbl.get_style_context().add_class('xattendo-guide-bullet')
            row.pack_start(dot, False, False, 0)
            row.pack_start(lbl, True, True, 0)
            bullets_box.pack_start(row, False, False, 0)
            bullet_labels.append(lbl)
        card.pack_start(bullets_box, True, True, 0)

        self._slide_titles.append(title_lbl)
        self._slide_subs.append(sub_lbl)
        self._slide_bullets.append(bullet_labels)
        return card

    def _build_slide_0(self) -> Gtk.Widget:
        """Slide 0: Top-Bar Pill & Controls."""
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        # Mock live pill
        pill_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        pill_row.set_halign(Gtk.Align.CENTER)
        mock_pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mock_pill.get_style_context().add_class('xattendo-pill')
        ring = ProgressRing(size=18)
        ring.set_state(0.65, 'active')
        ring.set_valign(Gtk.Align.CENTER)
        t_lbl = Gtk.Label(label='02:15:40')
        t_lbl.get_style_context().add_class('xattendo-pill-time')
        eta_lbl = Gtk.Label(label='→ 15:51')
        eta_lbl.get_style_context().add_class('xattendo-pill-eta')
        mock_pill.pack_start(ring, False, False, 0)
        mock_pill.pack_start(t_lbl, False, False, 0)
        mock_pill.pack_start(eta_lbl, False, False, 0)
        pill_row.pack_start(mock_pill, False, False, 0)
        self._ltr_widgets.append(mock_pill)

        # 3 state badges
        states_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        states_row.set_halign(Gtk.Align.CENTER)
        for text, cls in (
            ('● Active', 'status-active'),
            ('● Locked', 'status-locked'),
            ('✓ Done', 'status-active'),
        ):
            lbl = Gtk.Label(label=text)
            lbl.get_style_context().add_class('xattendo-status-pill')
            lbl.get_style_context().add_class(cls)
            states_row.pack_start(lbl, False, False, 0)
        self._ltr_widgets.append(states_row)

        wrap.pack_start(pill_row, False, False, 0)
        wrap.pack_start(states_row, False, False, 0)
        return self._build_slide_shell(wrap, bullet_count=4)

    def _build_slide_1(self) -> Gtk.Widget:
        """Slide 1: Daily Goal & Finish Time (12:45)."""
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        clock = Gtk.Label(label='03:18:15', xalign=0)
        clock.get_style_context().add_class('xattendo-mini-clock')
        badge = Gtk.Label(label='Done @ 15:51', xalign=1)
        badge.get_style_context().add_class('xattendo-eta-badge')
        top.pack_start(clock, True, True, 0)
        top.pack_end(badge, False, False, 0)
        self._ltr_widgets.append(top)

        bar = Gtk.ProgressBar()
        bar.set_fraction(0.65)
        bar.get_style_context().add_class('xattendo-progress')

        timeline = DayTimeline()
        now_dt = campus_now().replace(hour=13, minute=30, second=0, microsecond=0)
        win_start = now_dt.replace(hour=8, minute=0).timestamp()
        win_end = now_dt.replace(hour=20, minute=0).timestamp()
        segs = [
            (now_dt.replace(hour=9, minute=15).timestamp(), now_dt.replace(hour=11, minute=45).timestamp()),
            (now_dt.replace(hour=12, minute=20).timestamp(), now_dt.timestamp()),
        ]
        timeline.set_timeline(
            win_start,
            win_end,
            segs,
            now_dt.timestamp(),
            eta_ts=now_dt.replace(hour=15, minute=51).timestamp(),
        )
        self._ltr_widgets.append(timeline)

        wrap.pack_start(top, False, False, 0)
        wrap.pack_start(bar, False, False, 0)
        wrap.pack_start(timeline, False, False, 0)
        return self._build_slide_shell(wrap, bullet_count=3)

    def _build_slide_2(self) -> Gtk.Widget:
        """Slide 2: Current Day, Attendo Period & Sessions."""
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        today_strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        today_strip.get_style_context().add_class('xattendo-today-strip')
        dot = Gtk.Label(label='●')
        dot.get_style_context().add_class('xattendo-today-dot')
        date_lbl = Gtk.Label(label='Saturday, Nov 28', xalign=0)
        date_lbl.get_style_context().add_class('xattendo-today-date')
        day_pill = Gtk.Label(label='Day 4 of 7', xalign=1)
        day_pill.get_style_context().add_class('xattendo-day-pill')
        today_strip.pack_start(dot, False, False, 0)
        today_strip.pack_start(date_lbl, True, True, 0)
        today_strip.pack_end(day_pill, False, False, 0)
        self._ltr_widgets.append(today_strip)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        net_lbl = Gtk.Label(label='9h 41m of 30h', xalign=0)
        net_lbl.get_style_context().add_class('xattendo-mono-sm')
        pct_lbl = Gtk.Label(label='32%', xalign=1)
        pct_lbl.get_style_context().add_class('xattendo-pct-pill')
        top.pack_start(net_lbl, True, True, 0)
        top.pack_end(pct_lbl, False, False, 0)
        self._ltr_widgets.append(top)

        bar = Gtk.ProgressBar()
        bar.set_fraction(0.32)
        bar.get_style_context().add_class('xattendo-progress')

        days_bar = CountedDaysBar()
        days_bar.set_days(3, 7, current_day=4, today_done=False)
        self._ltr_widgets.append(days_bar)

        wrap.pack_start(today_strip, False, False, 0)
        wrap.pack_start(top, False, False, 0)
        wrap.pack_start(bar, False, False, 0)
        wrap.pack_start(days_bar, False, False, 2)
        return self._build_slide_shell(wrap, bullet_count=3)

    def _build_slide_3(self) -> Gtk.Widget:
        """Slide 3: Link Your Accounts (Works With Any Browser)."""
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        pills_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        pills_row.set_halign(Gtk.Align.CENTER)
        p1 = Gtk.Label(label='Attendo: ✓ Linked')
        p1.get_style_context().add_class('xattendo-login-pill')
        p1.get_style_context().add_class('linked')
        p2 = Gtk.Label(label='42 Intra: ✓ Linked')
        p2.get_style_context().add_class('xattendo-login-pill')
        p2.get_style_context().add_class('linked')
        pills_row.pack_start(p1, False, False, 0)
        pills_row.pack_start(p2, False, False, 0)
        self._ltr_widgets.append(pills_row)

        self.slide_login_btn = Gtk.Button()
        self.slide_login_btn.get_style_context().add_class('xattendo-btn-primary')
        self.slide_login_btn.set_halign(Gtk.Align.CENTER)
        self.slide_login_btn.connect('clicked', lambda *_: self.on_open_web_login('both'))

        wrap.pack_start(pills_row, False, False, 0)
        wrap.pack_start(self.slide_login_btn, False, False, 0)
        return self._build_slide_shell(wrap, bullet_count=3)

    def _on_language_selected(self, lang: str) -> None:
        norm = normalize_lang(lang)
        if self.config_service.config.language != norm:
            self.config_service.config.language = norm
            self.config_service.save(notify=True)
        self.apply_language(norm)

    def apply_language(self, lang: str) -> None:
        norm = normalize_lang(lang)
        apply_rtl_layout(self, is_rtl(norm), ltr_widgets=self._ltr_widgets)

        self.set_title(tr(norm, 'guide_win_title'))
        self.header_title_lbl.set_text(tr(norm, 'app_name'))
        self.slide_login_btn.set_label(tr(norm, 'web_login_btn'))

        for code, btn in self._lang_buttons.items():
            ctx = btn.get_style_context()
            ctx.remove_class('xattendo-btn')
            ctx.remove_class('xattendo-btn-primary')
            ctx.add_class('xattendo-btn-primary' if code == norm else 'xattendo-btn')

        slide_specs = [
            ('guide_s1_title', 'guide_s1_sub', ('guide_s1_b1', 'guide_s1_b2', 'guide_s1_b3', 'guide_s1_b4')),
            ('guide_s2_title', 'guide_s2_sub', ('guide_s2_b1', 'guide_s2_b2', 'guide_s2_b3')),
            ('guide_s3_title', 'guide_s3_sub', ('guide_s3_b1', 'guide_s3_b2', 'guide_s3_b3')),
            ('guide_s4_title', 'guide_s4_sub', ('guide_s4_b1', 'guide_s4_b2', 'guide_s4_b3')),
        ]
        for idx, (t_key, s_key, b_keys) in enumerate(slide_specs):
            self._slide_titles[idx].set_text(tr(norm, t_key))
            self._slide_subs[idx].set_text(tr(norm, s_key))
            for b_idx, b_key in enumerate(b_keys):
                self._slide_bullets[idx][b_idx].set_text(tr(norm, b_key))

        self._update_step_ui()

    def _update_step_ui(self) -> None:
        norm = self._lang()
        self.stack.set_visible_child_name(f'step-{self._step}')
        self.step_counter_lbl.set_text(
            tr(norm, 'guide_step_counter', current=self._step + 1, total=self.TOTAL_STEPS)
        )
        self.back_btn.set_label(tr(norm, 'guide_skip' if self._step == 0 else 'guide_back'))
        self.next_btn.set_label(
            tr(norm, 'guide_done' if self._step >= self.TOTAL_STEPS - 1 else 'guide_next')
        )
        for idx, dot in enumerate(self._step_dots):
            ctx = dot.get_style_context()
            if idx == self._step:
                ctx.add_class('active')
            else:
                ctx.remove_class('active')

    def _go_back(self) -> None:
        if self._step == 0:
            self.complete_and_close()
            return
        self._step = max(0, self._step - 1)
        self._update_step_ui()

    def _go_next(self) -> None:
        if self._step >= self.TOTAL_STEPS - 1:
            self.complete_and_close()
            return
        self._step = min(self.TOTAL_STEPS - 1, self._step + 1)
        self._update_step_ui()

    def open_guide(self, step: int = 0) -> None:
        self._step = max(0, min(self.TOTAL_STEPS - 1, int(step)))
        self.apply_language(self._lang())
        self._update_step_ui()
        self.show_all()
        self.present_with_time(Gtk.get_current_event_time() or Gdk.CURRENT_TIME)

    def complete_and_close(self) -> None:
        self.config_service.config.onboarding_completed = True
        self.config_service.save(notify=False)
        self.hide()
        if self.on_finished:
            self.on_finished()

    def _on_delete(self, _widget, _event) -> bool:
        self.complete_and_close()
        return True

    def _on_key_press(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.complete_and_close()
            return True
        return False
