"""Хранилище подписок на утренний дайджест (JSON, атомарная запись)."""

import json
import os
import tempfile
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
USERS_FILE = DATA_DIR / "users.json"

DEFAULT_TIME = "07:00"


def _default_user() -> dict:
    return {"time": DEFAULT_TIME, "enabled": True, "last_sent": None}


class SelectionStorage:
    """Выбор группы пользователями (data/users_all.json)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (DATA_DIR / "users_all.json")

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def get(self, chat_id: int | str) -> dict:
        return self._load().get(str(chat_id), {})

    def set_group(self, chat_id: int | str, course: str, gid: str) -> None:
        data = self._load()
        user = data.get(str(chat_id), {})
        user["course"], user["group"] = course, gid
        data[str(chat_id)] = user
        self._save(data)

    def all_chat_ids(self) -> list[str]:
        return list(self._load().keys())

    # --- утренний дайджест (общий бот) ---

    def get_or_create(self, chat_id: int | str,
                      first_name: str | None = None,
                      username: str | None = None) -> dict:
        data = self._load()
        user = data.get(str(chat_id))
        if user is None:
            user = {"time": "07:00", "digest_enabled": True,
                    "last_sent": None, "first_name": first_name or "",
                    "username": username or ""}
            data[str(chat_id)] = user
            self._save(data)
        else:
            # обновляем профиль, если изменился
            if first_name and user.get("first_name") != first_name:
                user["first_name"] = first_name
            if username is not None and user.get("username") != username:
                user["username"] = username
        user.setdefault("time", "07:00")
        user.setdefault("digest_enabled", True)
        return user

    def set_digest_time(self, chat_id: int | str, time_hhmm: str) -> dict:
        data = self._load()
        user = data.get(str(chat_id), {})
        user["time"] = time_hhmm
        data[str(chat_id)] = user
        self._save(data)
        return user

    def set_digest_enabled(self, chat_id: int | str, enabled: bool) -> dict:
        data = self._load()
        user = data.get(str(chat_id), {})
        user["digest_enabled"] = enabled
        data[str(chat_id)] = user
        self._save(data)
        return user

    def mark_sent(self, chat_id: int | str, iso_date: str) -> None:
        data = self._load()
        user = data.get(str(chat_id))
        if user is not None:
            user["last_sent"] = iso_date
            self._save(data)

    def digest_users(self) -> dict[str, dict]:
        return {cid: u for cid, u in self._load().items()
                if u.get("digest_enabled")}
