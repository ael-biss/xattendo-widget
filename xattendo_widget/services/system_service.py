"""Desktop notifications and browser URL launcher service."""

import shutil
import subprocess
import webbrowser

import gi
gi.require_version('Notify', '0.7')
from gi.repository import Notify

from xattendo_widget.constants import APP_NAME


class SystemService:
    def __init__(self) -> None:
        Notify.init(APP_NAME)

    def notify(
        self,
        title: str,
        body: str,
        enabled: bool = True,
        icon: str = 'appointment-soon',
    ) -> None:
        if not enabled:
            return
        try:
            notification = Notify.Notification.new(title, body, icon)
            notification.show()
        except Exception:
            pass

    @staticmethod
    def open_url(url: str) -> None:
        target = (url or '').strip()
        if not target:
            return
        try:
            if webbrowser.open(target):
                return
        except Exception:
            pass
        xdg = shutil.which('xdg-open')
        if xdg:
            try:
                subprocess.Popen(
                    [xdg, target],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except Exception:
                pass
