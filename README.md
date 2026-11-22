# Xattendo Desktop Widget

A 100% standalone, always-on-top desktop & GNOME Top Bar widget for **42 Logtime** and **1337 Attendo** — completely independent of any local web server, with zero `sudo` and zero GNOME Shell extensions required.

## Features

- **Built-in Live Session & `ft_lock` Counter**: Tracks your active X11 session via `loginctl` and subtracts `/run/42-lock/seat0.json` lock intervals in real time (`00:00:00` 1-second ticking clock, Current Sess, Gross Today, Locked). Also merges existing `~/.local/share/live_estimate/sessions.json` history read-only.
- **Direct 42 Intra & 1337 Attendo Linking**: Automatically reads your signed-in **Brave**, **Firefox**, or **Chrome** session cookies (using pure-Python decryption, zero `pip` packages) — or accepts an optional manual `student_token` / 42 login in Settings — to pull your **42 Intra** (`locations_stats.json`) and **1337 Attendo** period totals.
- **42 Logtime Popup Card**:
  - **Today's Active Time** hero clock with decimal hours badge, Current Session, Gross Today, and Locked Time.
  - **Attendo Period** progress bar (`%`, hours logged vs target, hours left).
  - **42 Intra** & **1337 Attendo** status cards with one-click `Link ↗` buttons when not signed in.
  - **This Week** & **This Month** summary cards.
- **GNOME Top Bar & Floating Pill Mode**: Docks cleanly in the GNOME top bar on X11 via XInput2 (non-overlapping with `salat-widget`), or floats anywhere on screen.
- **Sessions, Periods & Lock History Window**: Inspect recent sessions, Attendo period days, and today's lock intervals.
- **Multilingual UI**: **English**, **Français**, and **العربية** (full RTL layout).

## Install

```bash
make install
```

Compiles a bytecode-only executable to `~/.local/bin/xattendo-widget`, enables login autostart in `~/.config/autostart/xattendo-desktop-widget.desktop`, and launches the widget.

## Developer Commands

```bash
make test          # Run automated unit tests
make build         # Build bytecode-only dist/xattendo-widget.pyz (0 .py source files)
make install       # Build & install locally to ~/.local/bin/xattendo-widget + autostart
make uninstall     # Remove installed app, extracted assets, and autostart
make run           # Run directly from source
make stop          # Stop running widget
make sim-active    # Simulate active session + linked Intra & Attendo
make sim-locked    # Simulate locked workstation (amber)
make sim-done      # Simulate period target reached (green)
make sim-unlinked  # Simulate local session with unlinked Intra & Attendo
```
