#!/usr/bin/env python3
"""Entrypoint for the standalone Xattendo Desktop & GNOME Top Bar Widget."""

import argparse
import signal
from typing import Optional

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from xattendo_widget.services.account_linker import AccountLinker
from xattendo_widget.services.config_service import ConfigService
from xattendo_widget.services.session_tracker import SessionTracker
from xattendo_widget.services.system_service import SystemService
from xattendo_widget.services.update_service import UpdateService
from xattendo_widget.ui.pill_window import PillWindow
from xattendo_widget.ui.styles import install_css


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Standalone 42 Logtime & Attendo Desktop Widget')
    parser.add_argument(
        '--simulate',
        choices=['active', 'locked', 'done', 'unlinked', 'update'],
        default=None,
        help='Run a live visual simulation for active, locked, period done (green), unlinked, or update state',
    )
    return parser.parse_args()


class AppController:
    def __init__(self, simulate: Optional[str] = None) -> None:
        self.simulate = simulate
        self.config_service = ConfigService()
        self.session_tracker = SessionTracker()
        self.account_linker = AccountLinker()
        self.system_service = SystemService()
        self.update_service = UpdateService()
        self.pill: Optional[PillWindow] = None
        self._create_pill(check_updates=True)

    def _create_pill(
        self,
        initial_linked=None,
        initial_triggered_events=None,
        check_updates: bool = False,
    ) -> None:
        self.pill = PillWindow(
            config_service=self.config_service,
            session_tracker=self.session_tracker,
            account_linker=self.account_linker,
            system_service=self.system_service,
            update_service=self.update_service,
            simulate=self.simulate,
            on_top_bar_mode_changed=self._on_mode_changed,
            initial_linked=initial_linked,
            initial_triggered_events=initial_triggered_events,
            check_updates=check_updates,
        )

    def _on_mode_changed(self, _top_bar_enabled: bool) -> bool:
        linked = None
        triggered = None
        if self.pill is not None:
            linked = self.pill.linked_state
            triggered = set(self.pill.triggered_events)
            self.pill.cleanup()
            self.pill = None
        self._create_pill(
            initial_linked=linked,
            initial_triggered_events=triggered,
            check_updates=False,
        )
        return False


def main() -> None:
    args = parse_args()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    install_css()
    controller = AppController(simulate=args.simulate)
    try:
        Gtk.main()
    finally:
        if controller.pill is not None:
            controller.pill.cleanup()


if __name__ == '__main__':
    main()
