"""Cairo-rendered circular radial progress ring widget for the pill."""

import math

import cairo
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


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
