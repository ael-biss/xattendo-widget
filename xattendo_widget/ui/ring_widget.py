"""Cairo-rendered circular progress ring, daily activity timeline, and 7-day bar widgets."""

import datetime
import math
from typing import List, Optional, Tuple

import cairo
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from xattendo_widget.core.calculator import campus_now, campus_zone


class HeaderIcon(Gtk.DrawingArea):
    """Crisp Cairo-rendered header icon ('pin' or 'refresh') tinted by GTK CSS color."""

    def __init__(self, icon_name: str, size: int = 15) -> None:
        super().__init__()
        self._icon_name = icon_name
        self._size = size
        self._active = False
        self.set_size_request(size, size)
        self.connect('draw', self._on_draw)

    def set_active(self, active: bool) -> None:
        val = bool(active)
        if val != self._active:
            self._active = val
            self.queue_draw()

    def _on_draw(self, _widget, ctx: cairo.Context) -> bool:
        w = float(self.get_allocated_width())
        h = float(self.get_allocated_height())
        dim = min(w, h)
        if dim <= 2:
            return False

        rgba = self.get_style_context().get_color(self.get_state_flags())
        ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
        ctx.set_antialias(cairo.ANTIALIAS_BEST)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)

        cx = w / 2.0
        cy = h / 2.0
        s = dim / 16.0

        if self._icon_name == 'pin':
            ctx.save()
            ctx.translate(cx, cy)
            if not self._active:
                ctx.rotate(math.pi / 4.0)
            ctx.set_line_width(max(1.3, 1.5 * s))

            # Top cap + body + base flange
            ctx.move_to(-3.0 * s, -5.5 * s)
            ctx.line_to(3.0 * s, -5.5 * s)
            ctx.line_to(2.3 * s, -3.5 * s)
            ctx.line_to(2.3 * s, 0.2 * s)
            ctx.line_to(4.2 * s, 2.0 * s)
            ctx.line_to(-4.2 * s, 2.0 * s)
            ctx.line_to(-2.3 * s, 0.2 * s)
            ctx.line_to(-2.3 * s, -3.5 * s)
            ctx.close_path()
            if self._active:
                ctx.fill_preserve()
            ctx.stroke()

            # Needle
            ctx.move_to(0.0, 2.0 * s)
            ctx.line_to(0.0, 6.2 * s)
            ctx.stroke()
            ctx.restore()
            return False

        if self._icon_name == 'update':
            # Upward arrow inside a subtle circle
            r = 6.2 * s
            ctx.set_line_width(max(1.3, 1.4 * s))
            ctx.arc(cx, cy, r, 0.0, 2.0 * math.pi)
            ctx.stroke()

            ctx.move_to(cx, cy + 3.0 * s)
            ctx.line_to(cx, cy - 3.0 * s)
            ctx.stroke()

            ctx.move_to(cx - 2.6 * s, cy - 0.6 * s)
            ctx.line_to(cx, cy - 3.2 * s)
            ctx.line_to(cx + 2.6 * s, cy - 0.6 * s)
            ctx.stroke()
            return False

        # 'refresh' clockwise circular arrow (Lucide rotate-cw style)
        r = 5.2 * s
        ctx.set_line_width(max(1.3, 1.5 * s))
        start_a = 0.12 * math.pi
        end_a = 1.75 * math.pi
        ctx.arc(cx, cy, r, start_a, end_a)
        ctx.stroke()

        ex = cx + r * math.cos(end_a)
        ey = cy + r * math.sin(end_a)
        ctx.move_to(ex, ey - 3.0 * s)
        ctx.line_to(ex, ey)
        ctx.line_to(ex - 3.0 * s, ey)
        ctx.stroke()
        return False


class ProgressRing(Gtk.DrawingArea):
    """Crisp circular progress indicator with center dot (or emerald check when done)."""

    def __init__(self, size: int = 16) -> None:
        super().__init__()
        self._size = size
        self._fraction = 0.0
        self._state = 'active'  # 'active' | 'locked' | 'done'
        self.set_size_request(size, size)
        self.connect('draw', self._on_draw)

    def set_state(self, fraction: float, state: str) -> None:
        clamped = max(0.0, min(1.0, float(fraction)))
        norm_state = state if state in ('active', 'locked', 'done') else 'active'
        if norm_state != self._state or abs(clamped - self._fraction) >= 0.005:
            self._fraction = clamped
            self._state = norm_state
            self.queue_draw()

    def _on_draw(self, _widget, ctx: cairo.Context) -> bool:
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        dim = min(w, h)
        if dim <= 2:
            return False

        cx = w / 2.0
        cy = h / 2.0
        stroke_w = max(1.8, dim * 0.13)
        radius = (dim / 2.0) - stroke_w

        ctx.set_antialias(cairo.ANTIALIAS_BEST)

        # Track circle
        ctx.set_source_rgba(1.0, 1.0, 1.0, 0.20)
        ctx.set_line_width(stroke_w)
        ctx.arc(cx, cy, radius, 0, 2.0 * math.pi)
        ctx.stroke()

        if self._state == 'done':
            # Full emerald green ring + checkmark
            ctx.set_source_rgb(0.247, 0.725, 0.314)  # #3fb950
            ctx.set_line_width(stroke_w)
            ctx.arc(cx, cy, radius, 0, 2.0 * math.pi)
            ctx.stroke()

            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.set_line_width(max(1.6, dim * 0.12))
            ctx.move_to(cx - radius * 0.42, cy + radius * 0.02)
            ctx.line_to(cx - radius * 0.10, cy + radius * 0.36)
            ctx.line_to(cx + radius * 0.46, cy - radius * 0.32)
            ctx.stroke()
            return False

        # Active (sky cyan #38bdf8) or Locked (amber #d29922)
        if self._state == 'locked':
            r, g, b = (0.824, 0.600, 0.133)
        else:
            r, g, b = (0.220, 0.741, 0.973)

        # Progress arc starting at 12 o'clock (-pi/2)
        arc_frac = max(0.03, self._fraction)
        start_angle = -math.pi / 2.0
        end_angle = start_angle + arc_frac * 2.0 * math.pi
        ctx.set_source_rgb(r, g, b)
        ctx.set_line_width(stroke_w)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.arc(cx, cy, radius, start_angle, end_angle)
        ctx.stroke()

        # Center dot
        ctx.arc(cx, cy, max(1.8, dim * 0.14), 0, 2.0 * math.pi)
        ctx.fill()
        return False


def _rounded_rect(ctx: cairo.Context, x: float, y: float, w: float, h: float, r: float) -> None:
    r = min(r, w / 2.0, h / 2.0)
    if r <= 0 or w <= 0 or h <= 0:
        return
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2.0, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2.0)
    ctx.arc(x + r, y + h - r, r, math.pi / 2.0, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    ctx.close_path()


class DayTimeline(Gtk.DrawingArea):
    """Horizontal daily activity timeline with sky-blue active blocks and green 'now' marker."""

    def __init__(self) -> None:
        super().__init__()
        self._win_start: float = 0.0
        self._win_end: float = 1.0
        self._segments: List[Tuple[float, float]] = []
        self._now_ts: float = 0.0
        self._eta_ts: Optional[float] = None
        self.set_size_request(-1, 40)
        self.connect('draw', self._on_draw)

    def set_timeline(
        self,
        win_start: float,
        win_end: float,
        segments: List[Tuple[float, float]],
        now_ts: float,
        eta_ts: Optional[float] = None,
    ) -> None:
        self._win_start = float(win_start)
        self._win_end = max(float(win_start) + 1.0, float(win_end))
        self._segments = list(segments)
        self._now_ts = float(now_ts)
        self._eta_ts = float(eta_ts) if eta_ts is not None else None
        self.queue_draw()

    def _on_draw(self, _widget, ctx: cairo.Context) -> bool:
        w = float(self.get_allocated_width())
        h = float(self.get_allocated_height())
        if w <= 10 or h <= 10:
            return False

        bar_h = 22.0
        span = max(1.0, self._win_end - self._win_start)

        # Background track
        ctx.set_source_rgb(0.137, 0.180, 0.247)  # #232e3f
        _rounded_rect(ctx, 0.0, 0.0, w, bar_h, 5.0)
        ctx.fill()

        # Active sky-blue blocks
        ctx.set_source_rgb(0.294, 0.722, 0.941)  # #4bb8f0
        for a, b in self._segments:
            x1 = max(0.0, min(w, ((a - self._win_start) / span) * w))
            x2 = max(0.0, min(w, ((b - self._win_start) / span) * w))
            seg_w = max(2.0, x2 - x1)
            if x1 + seg_w > w:
                seg_w = max(1.0, w - x1)
            _rounded_rect(ctx, x1, 0.0, seg_w, bar_h, 4.0)
            ctx.fill()

        # Green 'now' marker
        if self._win_start <= self._now_ts <= self._win_end:
            nx = ((self._now_ts - self._win_start) / span) * w
            nx = max(1.0, min(w - 2.0, nx))
            ctx.set_source_rgb(0.204, 0.827, 0.600)  # #34d399
            ctx.rectangle(nx - 1.0, 0.0, 2.0, bar_h)
            ctx.fill()

        # Subtle dashed emerald 'ETA' goal marker
        if self._eta_ts is not None and self._win_start <= self._eta_ts <= self._win_end:
            ex = ((self._eta_ts - self._win_start) / span) * w
            ex = max(2.0, min(w - 2.0, ex))
            ctx.save()
            ctx.set_source_rgba(0.204, 0.827, 0.600, 0.85)
            ctx.set_line_width(1.5)
            ctx.set_dash([3.0, 2.5])
            ctx.move_to(ex, 0.0)
            ctx.line_to(ex, bar_h)
            ctx.stroke()
            ctx.set_dash([])
            ctx.arc(ex, 2.5, 2.2, 0.0, 2.0 * math.pi)
            ctx.fill()
            ctx.restore()

        # Time tick labels
        zone = campus_zone()
        ctx.select_font_face('DejaVu Sans Mono', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(10.0)
        ctx.set_source_rgb(0.392, 0.455, 0.545)  # #64748b

        for idx in range(4):
            frac = idx / 3.0
            tick_ts = self._win_start + frac * span
            label = campus_now(datetime.datetime.fromtimestamp(tick_ts, zone)).strftime('%H:%M')
            ext = ctx.text_extents(label)
            if idx == 0:
                tx = 0.0
            elif idx == 3:
                tx = max(0.0, w - ext.width)
            else:
                tx = max(0.0, min(w - ext.width, frac * w - ext.width / 2.0))
            ctx.move_to(tx, bar_h + 13.0)
            ctx.show_text(label)

        return False


class CountedDaysBar(Gtk.DrawingArea):
    """7-segment horizontal progress indicator for counted Attendo days."""

    def __init__(self) -> None:
        super().__init__()
        self._counted = 0
        self._total = 7
        self.set_size_request(-1, 6)
        self.connect('draw', self._on_draw)

    def set_days(self, counted: int, total: int = 7) -> None:
        self._counted = max(0, int(counted))
        self._total = max(1, int(total))
        self.queue_draw()

    def _on_draw(self, _widget, ctx: cairo.Context) -> bool:
        w = float(self.get_allocated_width())
        h = float(self.get_allocated_height())
        if w <= 10 or h <= 2:
            return False

        gap = 4.0
        seg_h = min(4.0, h)
        y = (h - seg_h) / 2.0
        seg_w = max(4.0, (w - gap * (self._total - 1)) / self._total)

        for i in range(self._total):
            x = i * (seg_w + gap)
            if i < self._counted:
                ctx.set_source_rgb(0.294, 0.722, 0.941)  # #4bb8f0
            else:
                ctx.set_source_rgb(0.153, 0.204, 0.275)  # #273446
            _rounded_rect(ctx, x, y, seg_w, seg_h, 2.0)
            ctx.fill()

        return False
