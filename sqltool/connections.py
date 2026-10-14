"""Saved connections: metadata in JSON, passwords in Windows Credential Manager (keyring)."""
import json
import os
import pickle
import time
from dataclasses import dataclass, asdict, fields

from . import APP_NAME
from .settings import app_data_dir

CONNECTIONS_FILE = os.path.join(app_data_dir(), "connections.json")
LEGACY_PKL = os.path.join(os.path.expanduser("~"), "conn_details.pkl")


@dataclass
class ConnInfo:
    server: str
    database: str = "master"
    auth: str = "sql"               # "sql" | "windows"
    username: str = ""
    driver: str = ""                # empty = auto-detect
    encrypt: bool = False
    trust_cert: bool = True
    alias: str = ""
    last_used: float = 0.0

    @property
    def key(self):
        return (self.server.lower(), self.database.lower(), self.auth, self.username.lower())

    @property
    def label(self):
        return self.alias or f"{self.server} / {self.database}"

    @property
    def secret_id(self):
        return f"{self.server}|{self.username}"


def _keyring():
    import keyring
    return keyring


def get_password(info):
    if info.auth != "sql":
        return ""
    try:
        return _keyring().get_password(APP_NAME, info.secret_id) or ""
    except Exception:
        return ""


def set_password(info, pwd):
    if info.auth != "sql":
        return
    _keyring().set_password(APP_NAME, info.secret_id, pwd)


def _delete_password(info):
    try:
        _keyring().delete_password(APP_NAME, info.secret_id)
    except Exception:
        pass


class ConnectionStore:
    def __init__(self, path=CONNECTIONS_FILE):
        self.path = path
        self.items = self._read()

    def _read(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return []
        known = {f.name for f in fields(ConnInfo)}
        return [ConnInfo(**{k: v for k, v in d.items() if k in known})
                for d in raw if isinstance(d, dict) and d.get("server")]

    def _write(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([asdict(c) for c in self.items], f, indent=2)
        os.replace(tmp, self.path)

    def sorted(self):
        return sorted(self.items, key=lambda c: (-c.last_used, c.label.lower()))

    def find(self, key):
        return next((c for c in self.items if c.key == key), None)

    def upsert(self, info, password=None):
        """Insert or replace (by server/db/auth/user). Password is updated when given."""
        existing = self.find(info.key)
        if existing:
            self.items.remove(existing)
        self.items.append(info)
        if password is not None:
            set_password(info, password)
        self._write()

    def touch(self, info):
        info.last_used = time.time()
        if self.find(info.key):
            self._write()

    def delete(self, info):
        self.items = [c for c in self.items if c.key != info.key]
        # only drop the secret if no other saved entry uses the same server|user
        if not any(c.secret_id == info.secret_id for c in self.items):
            _delete_password(info)
        self._write()

    def migrate_legacy(self, pkl_path=LEGACY_PKL):
        """One-time import of v3's ~/conn_details.pkl. Returns number migrated."""
        if not os.path.exists(pkl_path):
            return 0
        with open(pkl_path, "rb") as f:
            data = pickle.load(f)          # the user's own file written by v3
        count = 0
        for d in data if isinstance(data, list) else []:
            if not isinstance(d, dict) or not d.get("server"):
                continue
            info = ConnInfo(server=d["server"], database=d.get("database", "master"),
                            username=d.get("uid", ""))
            if not self.find(info.key):
                self.items.append(info)
                set_password(info, d.get("pwd", ""))
                count += 1
        self._write()
        os.replace(pkl_path, pkl_path + ".bak")
        return count
