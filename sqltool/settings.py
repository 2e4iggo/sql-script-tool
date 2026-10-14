"""User settings persisted as JSON in %APPDATA%\\SQLScriptTool\\settings.json."""
import json
import os
from dataclasses import dataclass, field, asdict, fields

from . import APP_NAME


def app_data_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


SETTINGS_FILE = os.path.join(app_data_dir(), "settings.json")


@dataclass
class Settings:
    # Script output
    grant_roles: list = field(default_factory=lambda: ["SDA_ROLE", "HR_ROLE"])
    include_grants: bool = True
    header_mode: str = "drop_create"        # drop_create | create_or_alter | definition
    include_separator: bool = True
    # Table script
    table_if_not_exists: bool = True
    varchar_to_nvarchar: bool = True
    table_indexes: bool = False
    table_foreign_keys: bool = False
    table_check_constraints: bool = False
    # Copy
    compact_copy: bool = True               # v3 behaviour: strip lines, drop blanks
    # Import
    import_default_mode: str = "create_append"
    import_schema: str = "dbo"
    # UI
    theme: str = "bootstrap-dark"
    geometry: str = "1280x800"
    show_log: bool = True

    @classmethod
    def load(cls, path=SETTINGS_FILE):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path=SETTINGS_FILE):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
        os.replace(tmp, path)
