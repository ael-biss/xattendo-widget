"""Centralized deep-obsidian & cyan/emerald GTK3 stylesheet and icon helpers."""

import os
from typing import Optional

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gdk, GdkPixbuf, Gtk

from xattendo_widget.constants import ALERT_ICON_PATH, DEFAULT_ICON_PATH, DONE_ICON_PATH

APP_CSS = b"""
* {
    font-family: "Ubuntu", "Noto Sans Arabic", "Inter", "Cantarell", "DejaVu Sans", sans-serif;
}

window.xattendo-transparent {
    background-color: transparent;
}

window.xattendo-window {
    background-color: #090c10;
    color: #f0f6fc;
}

/* Floating / Top-Bar Pill */
.xattendo-pill {
    background-color: #1f2226;
    border: 1px solid #32373d;
    border-radius: 999px;
    padding: 5px 13px;
    color: #f0f6fc;
}

.xattendo-pill:hover,
.xattendo-pill.xattendo-pill-hover {
    background-color: #282c31;
    border-color: #38bdf8;
}

.xattendo-pill.top-bar-mode {
    background-color: #1f2226;
    border: 1px solid #32373d;
    border-radius: 999px;
    padding: 2px 11px;
}

.xattendo-pill.top-bar-mode:hover,
.xattendo-pill.top-bar-mode.xattendo-pill-hover {
    background-color: #282c31;
    border-color: #38bdf8;
}

/* Period Target Reached (Emerald Green) */
.xattendo-pill.goal-reached {
    background-color: #0d1f1a;
    border: 1px solid #3fb950;
}

.xattendo-pill.goal-reached:hover,
.xattendo-pill.goal-reached.xattendo-pill-hover {
    background-color: #122b24;
    border-color: #56d364;
}

/* Locked / Warning (Amber) */
.xattendo-pill.locked-mode {
    background-color: #21190c;
    border: 1px solid #d29922;
}

.xattendo-pill.locked-mode:hover,
.xattendo-pill.locked-mode.xattendo-pill-hover {
    background-color: #2d2210;
    border-color: #e3b341;
}

.xattendo-pill-name {
    font-weight: 700;
    font-size: 12.5px;
    color: #38bdf8;
}

.xattendo-pill.top-bar-mode .xattendo-pill-name {
    font-size: 11.5px;
}

.xattendo-pill.goal-reached .xattendo-pill-name {
    color: #3fb950;
}

.xattendo-pill.locked-mode .xattendo-pill-name {
    color: #d29922;
}

.xattendo-pill-sep {
    color: #475569;
    font-size: 11px;
}

.xattendo-pill-time {
    font-family: "JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono", monospace;
    font-weight: 700;
    font-size: 12.5px;
    color: #f0f6fc;
}

.xattendo-pill.top-bar-mode .xattendo-pill-time {
    font-size: 11.5px;
}

/* Popup & Card Surfaces (Minimalist 42 Logtime mockup) */
.xattendo-card {
    background-color: #10151c;
    border: 1px solid #24303e;
    border-radius: 16px;
    padding: 0px;
    color: #e8eef5;
}

.xattendo-card-body {
    padding: 14px 14px 12px 14px;
}

.xattendo-panel {
    background-color: #18202c;
    border: 1px solid #232e3d;
    border-radius: 12px;
    padding: 13px 14px;
}

.xattendo-inset-card {
    background-color: #10151c;
    border: 1px solid #1e2734;
    border-radius: 10px;
    padding: 9px 10px;
}

.xattendo-section {
    background-color: #11161d;
    border: 1px solid #202833;
    border-radius: 11px;
    padding: 11px 12px;
}

.xattendo-mini-card {
    background-color: #18202c;
    border: 1px solid #232e3d;
    border-radius: 12px;
    padding: 12px 13px;
}

.xattendo-badge-42 {
    background-color: #e8eef5;
    color: #0d1218;
    font-weight: 900;
    font-size: 13px;
    border-radius: 8px;
    padding: 6px 8px;
}

.xattendo-title {
    font-weight: 700;
    font-size: 14.5px;
    color: #f0f6fc;
}

.xattendo-version-tag {
    font-family: "JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono", monospace;
    font-size: 9.5px;
    font-weight: 600;
    color: #8b97a8;
    background-color: #18202c;
    border: 1px solid #263344;
    border-radius: 6px;
    padding: 1px 5px;
}

.xattendo-subtitle {
    font-family: "JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono", monospace;
    font-size: 11px;
    color: #8b97a8;
}

.xattendo-section-title {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.6px;
    color: #8b97a8;
}

.xattendo-panel-label {
    font-size: 11.5px;
    font-weight: 500;
    color: #94a3b8;
}

.xattendo-field-label {
    font-size: 12.5px;
    font-weight: 600;
    color: #e6edf3;
}

.xattendo-hint {
    font-size: 11px;
    color: #8b97a8;
}

.xattendo-pace-text {
    font-size: 11px;
    color: #94a3b8;
}

.xattendo-big-metric {
    font-size: 20px;
    font-weight: 700;
    color: #f0f6fc;
}

.xattendo-header-icon-btn {
    background-image: none;
    background-color: transparent;
    color: #8b97a8;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 4px 6px;
    min-height: 26px;
    min-width: 26px;
    font-size: 13px;
    box-shadow: none;
}

.xattendo-header-icon-btn:hover {
    background-color: #1c2634;
    color: #f0f6fc;
}

.xattendo-header-icon-btn.pinned {
    color: #4bb8f0;
    background-color: #132538;
}

.xattendo-bottom-nav {
    border-top: 1px solid #222d3b;
}

.xattendo-nav-btn {
    background-image: none;
    background-color: transparent;
    color: #8b97a8;
    border: none;
    border-top: 2px solid transparent;
    border-radius: 0px;
    padding: 11px 8px;
    font-size: 12px;
    font-weight: 600;
    box-shadow: none;
}

.xattendo-nav-btn:hover {
    color: #e8eef5;
}

.xattendo-nav-btn.active {
    color: #4bb8f0;
    border-top: 2px solid #4bb8f0;
}

/* Header Status Pill */
.xattendo-status-pill {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.4px;
    padding: 3px 9px;
    border-radius: 999px;
    border: 1px solid #263244;
    background-color: #161d26;
    color: #7d8590;
}

.xattendo-status-pill.status-active {
    background-color: #11261a;
    border-color: #235334;
    color: #3fb950;
}

.xattendo-status-pill.status-locked {
    background-color: #261b0b;
    border-color: #6b4b12;
    color: #d29922;
}

/* Hero Attendance Card */
.xattendo-hero-card {
    background-color: #131a24;
    border: 1px solid #1e4664;
    border-radius: 12px;
    padding: 13px;
}

.xattendo-hero-card.goal-reached {
    background-color: #0e1e19;
    border-color: #235334;
}

.xattendo-hero-card.locked-mode {
    background-color: #1f170c;
    border-color: #6b4b12;
}

.xattendo-hero-clock {
    font-family: "JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono", monospace;
    font-size: 33px;
    font-weight: 800;
    color: #e8eef5;
}

.xattendo-decimal-badge {
    background-color: #102a3c;
    color: #38bdf8;
    border: 1px solid #1e4d6b;
    border-radius: 6px;
    padding: 2px 7px;
    font-family: "JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono", monospace;
    font-size: 11px;
    font-weight: 700;
}

.xattendo-pct-pill {
    font-family: "JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono", monospace;
    font-size: 11px;
    font-weight: 700;
    color: #38bdf8;
}

.xattendo-daily-row {
    margin-top: 2px;
    margin-bottom: 2px;
}

.xattendo-hero-divider {
    background-color: #202833;
    min-height: 1px;
}

.xattendo-stat-label {
    font-size: 10px;
    color: #7d8590;
}

.xattendo-stat-val {
    font-family: "JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono", monospace;
    font-size: 12px;
    font-weight: 700;
    color: #c9d1d9;
}

.xattendo-stat-green {
    color: #3fb950;
}

.xattendo-stat-amber {
    color: #d29922;
}

.xattendo-stat-cyan {
    color: #38bdf8;
}

.xattendo-mini-clock {
    font-family: "JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono", monospace;
    font-size: 13.5px;
    font-weight: 700;
    color: #f0f6fc;
}

.xattendo-mono-sm {
    font-family: "JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono", monospace;
    font-size: 11.5px;
    font-weight: 600;
    color: #e6edf3;
}

/* Progress Bars */
progressbar.xattendo-progress trough {
    background-color: #253041;
    border: none;
    border-radius: 999px;
    min-height: 6px;
}

progressbar.xattendo-progress progress {
    background-color: #4bb8f0;
    border: none;
    border-radius: 999px;
    min-height: 6px;
}

progressbar.xattendo-progress.complete progress {
    background-color: #34d399;
}

/* Icon & Close Buttons */
.xattendo-icon-btn {
    background-image: none;
    background-color: #11161d;
    color: #c9d1d9;
    border: 1px solid #243040;
    border-radius: 7px;
    padding: 2px 7px;
    min-height: 24px;
    min-width: 24px;
    font-size: 12px;
    font-weight: 700;
    box-shadow: none;
}

.xattendo-icon-btn:hover {
    background-color: #1a2330;
    border-color: #38bdf8;
    color: #38bdf8;
}

.xattendo-link-btn {
    background-image: none;
    background-color: #132234;
    color: #38bdf8;
    border: 1px solid #1e4664;
    border-radius: 7px;
    padding: 2px 8px;
    min-height: 22px;
    font-size: 11px;
    font-weight: 700;
    box-shadow: none;
}

.xattendo-link-btn:hover {
    background-color: #1a314a;
    border-color: #38bdf8;
    color: #ffffff;
}

/* Segmented Tabs */
.xattendo-tab-btn {
    background-image: none;
    background-color: #11161d;
    color: #7d8590;
    border: 1px solid #243040;
    border-radius: 8px;
    padding: 5px 10px;
    font-size: 11.5px;
    font-weight: 600;
    box-shadow: none;
}

.xattendo-tab-btn:hover {
    background-color: #1a2330;
    color: #f0f6fc;
}

.xattendo-tab-btn.active {
    background-color: #13293d;
    border-color: #38bdf8;
    color: #ffffff;
}

/* Inputs & Switches */
entry,
spinbutton,
spinbutton entry {
    background-image: none;
    background-color: #090c10;
    color: #f0f6fc;
    border: 1px solid #2b384a;
    border-radius: 8px;
    padding: 4px 8px;
    box-shadow: none;
    font-size: 12.5px;
}

spinbutton {
    padding: 0;
}

spinbutton entry {
    border: none;
    border-radius: 8px 0 0 8px;
}

spinbutton button {
    background-image: none;
    background-color: #161d26;
    color: #e2e8f0;
    border: none;
    border-left: 1px solid #2b384a;
    box-shadow: none;
    padding: 4px 8px;
}

spinbutton button:hover {
    background-color: #223044;
    color: #38bdf8;
}

entry:focus,
spinbutton:focus {
    border-color: #38bdf8;
}

switch {
    background-color: #263244;
    border: 1px solid #334155;
    border-radius: 999px;
    color: transparent;
    min-width: 42px;
    min-height: 22px;
}

switch:checked {
    background-color: #38bdf8;
    border-color: #38bdf8;
}

switch slider {
    background-color: #f8fafc;
    border-radius: 999px;
    min-width: 16px;
    min-height: 16px;
    margin: 2px;
}

/* Action Buttons */
.xattendo-btn {
    background-image: none;
    background-color: #11161d;
    color: #e6edf3;
    border: 1px solid #243040;
    border-radius: 9px;
    padding: 5px 10px;
    font-size: 11.5px;
    font-weight: 600;
    box-shadow: none;
}

.xattendo-btn:hover {
    background-color: #1a2330;
    border-color: #38bdf8;
    color: #ffffff;
}

.xattendo-btn-primary {
    background-image: none;
    background-color: #0284c7;
    color: #ffffff;
    border: 1px solid #38bdf8;
    border-radius: 9px;
    padding: 5px 10px;
    font-size: 11.5px;
    font-weight: 700;
    box-shadow: none;
}

.xattendo-btn-primary:hover {
    background-color: #0ea5e9;
}

.xattendo-btn-danger:hover {
    background-color: #3b1820;
    border-color: #f85149;
    color: #fca5a5;
}

.xattendo-btn-pinned {
    background-color: #102a3c;
    border-color: #38bdf8;
    color: #38bdf8;
}

/* History & Period Tables */
.xattendo-sched-header {
    background-color: #11161d;
    border-bottom: 1px solid #243040;
    padding: 8px 10px;
    border-radius: 10px 10px 0 0;
}

.xattendo-sched-th {
    font-size: 11.5px;
    font-weight: 700;
    color: #38bdf8;
}

.xattendo-sched-row {
    padding: 6px 10px;
    border-radius: 8px;
}

.xattendo-sched-row-alt {
    background-color: #11161d;
}

.xattendo-sched-row-today {
    background-color: #102a3c;
    border: 1px solid #38bdf8;
}

.xattendo-sched-cell {
    font-size: 12px;
    color: #e6edf3;
}

.xattendo-sched-cell-mono {
    font-family: "JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono", monospace;
    font-size: 12px;
    font-weight: 600;
    color: #f0f6fc;
}
"""


def install_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_data(APP_CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def enable_rgba(window: Gtk.Window) -> None:
    window.set_app_paintable(True)
    screen = window.get_screen()
    visual = screen.get_rgba_visual()
    if visual is not None and screen.is_composited():
        window.set_visual(visual)


def load_state_icon(size: int, state: str = 'normal') -> Optional[GdkPixbuf.Pixbuf]:
    if state == 'done':
        path = DONE_ICON_PATH
    elif state == 'alert':
        path = ALERT_ICON_PATH
    else:
        path = DEFAULT_ICON_PATH
    if os.path.exists(path):
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
        except Exception:
            pass
    return None


def apply_rtl_layout(root: Gtk.Widget, rtl: bool, ltr_widgets=()) -> None:
    """Recursively apply RTL or LTR direction across a GTK3 widget tree."""
    direction = Gtk.TextDirection.RTL if rtl else Gtk.TextDirection.LTR
    Gtk.Widget.set_default_direction(direction)
    ltr_set = set(ltr_widgets)

    def _walk(widget: Gtk.Widget) -> None:
        if widget in ltr_set:
            widget.set_direction(Gtk.TextDirection.LTR)
            return
        widget.set_direction(direction)
        if isinstance(widget, Gtk.Label) and widget.get_line_wrap():
            widget.set_justify(Gtk.Justification.RIGHT if rtl else Gtk.Justification.LEFT)
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                _walk(child)

    _walk(root)
    root.queue_resize()
