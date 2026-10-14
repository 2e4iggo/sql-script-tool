"""Settings dialog for options not on the main toolbar."""
import tkinter as tk

import ttkbootstrap as tb

from ..importer import MODES


class SettingsDialog(tb.Toplevel):
    def __init__(self, app):
        super().__init__(title="Settings", transient=app.root, resizable=(False, False))
        self.app = app
        s = app.settings
        body = tb.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        self.roles = tk.StringVar(value=", ".join(s.grant_roles))
        self.compact = tk.BooleanVar(value=s.compact_copy)
        self.schema = tk.StringVar(value=s.import_schema)
        self.mode = tk.StringVar(value=MODES.get(s.import_default_mode, MODES["create_append"]))

        r = 0
        tb.Label(body, text="SCRIPTS", font=("Segoe UI", 9, "bold"), bootstyle="primary").grid(
            row=r, column=0, columnspan=2, sticky="w")
        r += 1
        tb.Label(body, text="Grant roles").grid(row=r, column=0, sticky="w", pady=6, padx=(0, 12))
        tb.Entry(body, textvariable=self.roles, width=40).grid(row=r, column=1, sticky="ew")
        r += 1
        tb.Label(body, text="Comma-separated. Used for GRANT SELECT / EXEC lines.",
                 bootstyle="secondary", font=("Segoe UI", 8)).grid(row=r, column=1, sticky="w")
        r += 1
        tb.Checkbutton(body, text="Compact copy (strip indentation and blank lines)",
                       variable=self.compact, bootstyle="round-toggle").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(10, 4))
        r += 1

        tb.Separator(body).grid(row=r, column=0, columnspan=2, sticky="ew", pady=12)
        r += 1
        tb.Label(body, text="IMPORT", font=("Segoe UI", 9, "bold"), bootstyle="primary").grid(
            row=r, column=0, columnspan=2, sticky="w")
        r += 1
        tb.Label(body, text="Default schema").grid(row=r, column=0, sticky="w", pady=6, padx=(0, 12))
        tb.Entry(body, textvariable=self.schema).grid(row=r, column=1, sticky="ew")
        r += 1
        tb.Label(body, text="Default mode").grid(row=r, column=0, sticky="w", pady=6, padx=(0, 12))
        tb.Combobox(body, textvariable=self.mode, values=list(MODES.values()),
                    state="readonly").grid(row=r, column=1, sticky="ew")
        r += 1

        btns = tb.Frame(body)
        btns.grid(row=r, column=0, columnspan=2, sticky="e", pady=(18, 0))
        tb.Button(btns, text="Cancel", bootstyle="secondary-outline", command=self.destroy).pack(side="right")
        tb.Button(btns, text="Save", bootstyle="primary", command=self.save).pack(side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self.save())
        self.grab_set()
        self.place_window_center() if hasattr(self, "place_window_center") else None

    def save(self):
        s = self.app.settings
        s.grant_roles = [r.strip() for r in self.roles.get().split(",") if r.strip()]
        s.compact_copy = self.compact.get()
        s.import_schema = self.schema.get().strip() or "dbo"
        inv = {v: k for k, v in MODES.items()}
        s.import_default_mode = inv.get(self.mode.get(), "create_append")
        self.app.save_settings()
        self.app.workspace.refresh_roles_label()
        self.app.log("Settings saved", "ok")
        self.destroy()
