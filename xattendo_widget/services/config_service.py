"""User configuration persistence with change listeners."""

import json
import os
from typing import Callable, List

from xattendo_widget.constants import CONFIG_DIR, CONFIG_FILE
from xattendo_widget.models import UserConfig


class ConfigService:
    def __init__(self) -> None:
        self._config: UserConfig = self._load_from_disk()
        self._listeners: List[Callable[[UserConfig], None]] = []

    @property
    def config(self) -> UserConfig:
        return self._config

    def subscribe(self, callback: Callable[[UserConfig], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[UserConfig], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def save(self, notify: bool = True) -> None:
        try:
            os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._config.to_dict(), f, indent=2, ensure_ascii=False)
            os.chmod(CONFIG_FILE, 0o600)
        except Exception:
            pass

        if notify:
            for cb in list(self._listeners):
                try:
                    cb(self._config)
                except Exception:
                    pass

    def _load_from_disk(self) -> UserConfig:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    parsed = json.load(f)
                if isinstance(parsed, dict):
                    return UserConfig.from_dict(parsed)
            except Exception:
                pass
        return UserConfig()
