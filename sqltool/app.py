"""Main window: screens, menu, log panel, status bar, background-job plumbing."""
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as tb

from . import APP_TITLE, VERSION
from .connections import ConnectionStore
from .settings import Settings
from .worker import run_bg

DARK_THEME, LIGHT_THEME = "bootstrap-dark", "bootstrap-light"
LOG_COLORS = {"ok": "#479f76", "warn": "#e0a800", "err": "#e35d6a", "info": None}
LOG_ICONS = {"ok": "✓", "warn": "⚠", "err": "✗", "info": "·"}


class App:
    def __init__(self):
        self.settings = Settings.load()
        if self.settings.theme not in (DARK_THEME, LIGHT_THEME):
            self.settings.theme = DARK_THEME
        self.root = tb.Window(title=f"{APP_TITLE} {VERSION}", themename=self.settings.theme,
                              minsize=(900, 560))
        self._restore_geometry()
        self._set_icon()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self.store = ConnectionStore()
        self.db = None
        self.conn_info = None
        self.password = ""
        self.job = None
        self._busy_widgets = []

        self._build_menu()
        self._build_layout()
        self._bind_keys()

        from .ui.connect_screen import ConnectScreen
        from .ui.workspace_screen import WorkspaceScreen
        self.connect_screen = ConnectScreen(self.screens, self)
        self.workspace = WorkspaceScreen(self.screens, self)
        self.apply_theme_colors()
        self.show_connect()
        self.root.after(50, self._migrate_legacy)

    # ── layout ────────────────────────────────────────────────────
    def _build_menu(self):
        m = tk.Menu(self.root)
        f = tk.Menu(m, tearoff=False)
        f.add_command(label="Import data…", accelerator="Ctrl+I", command=self.open_import)
        f.add_command(label="Save script…", accelerator="Ctrl+S",
                      command=lambda: self.workspace.save_script())
        f.add_separator()
        f.add_command(label="Settings…", command=self.open_settings)
        f.add_separator()
        f.add_command(label="Exit", command=self.quit)
        m.add_cascade(label="File", menu=f)

        v = tk.Menu(m, tearoff=False)
        self.dark_var = tk.BooleanVar(value=self.settings.theme == DARK_THEME)
        self.log_var = tk.BooleanVar(value=self.settings.show_log)
        v.add_checkbutton(label="Dark theme", variable=self.dark_var, command=self.toggle_theme)
        v.add_checkbutton(label="Show log", variable=self.log_var, command=self.toggle_log,
                          accelerator="Ctrl+L")
        m.add_cascade(label="View", menu=v)

        c = tk.Menu(m, tearoff=False)
        c.add_command(label="Switch connection", command=self.show_connect)
        c.add_command(label="Refresh objects", accelerator="F5",
                      command=lambda: self.workspace.refresh_objects())
        m.add_cascade(label="Connection", menu=c)
        self.root.config(menu=m)

    def _build_layout(self):
        status = tb.Frame(self.root, padding=(10, 3))
        status.pack(side="bottom", fill="x")
        self.status_lbl = tb.Label(status, text="Ready", bootstyle="secondary", anchor="w")
        self.status_lbl.pack(side="left", fill="x", expand=True)
        self.progress = tb.Progressbar(status, mode="indeterminate", length=160,
                                       bootstyle="info-striped")
        self.cancel_btn = tb.Button(status, text="Cancel", bootstyle="danger-link",
                                    command=self.cancel_job)
        tb.Separator(self.root).pack(side="bottom", fill="x")

        self.vpane = tb.Panedwindow(self.root, orient="vertical")
        self.vpane.pack(fill="both", expand=True)
        self.screens = tb.Frame(self.vpane)
        self.vpane.add(self.screens, weight=5)

        self.log_frame = tb.Frame(self.vpane, padding=(10, 4, 10, 6))
        hdr = tb.Frame(self.log_frame)
        hdr.pack(fill="x")
        tb.Label(hdr, text="LOG", font=("Segoe UI", 8, "bold"), bootstyle="secondary").pack(side="left")
        tb.Button(hdr, text="Clear", bootstyle="secondary-link", padding=(4, 0),
                  command=self.clear_log).pack(side="right")
        self.log_text = tk.Text(self.log_frame, height=6, font=("Consolas", 9), relief="flat",
                                bd=0, padx=6, pady=4, state="disabled", wrap="word",
                                highlightthickness=0)
        self.log_text.pack(fill="both", expand=True)
        for k, color in LOG_COLORS.items():
            if color:
                self.log_text.tag_configure(k, foreground=color)
        self.log_text.tag_configure("time", foreground="#6c757d")
        if self.settings.show_log:
            self.vpane.add(self.log_frame, weight=1)

    def _bind_keys(self):
        r = self.root
        r.bind_all("<Control-i>", lambda e: self.open_import())
        r.bind_all("<Control-l>", lambda e: (self.log_var.set(not self.log_var.get()), self.toggle_log()))

    def _set_icon(self):
        # assets/ sits next to the sqltool package; inside the PyInstaller build it's under _MEIPASS
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ico = os.path.join(base, "assets", "app.ico")
        if os.path.exists(ico):
            try:
                self.root.iconbitmap(default=ico)    # default= applies to dialogs too
            except tk.TclError:
                pass

    def _restore_geometry(self):
        """Restore the saved size, clamped so the window always fits on the current screen."""
        import re
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight() - 60   # taskbar
        m = re.match(r"(\d+)x(\d+)(?:\+(-?\d+)\+(-?\d+))?", self.settings.geometry or "")
        w, h = (int(m.group(1)), int(m.group(2))) if m else (1280, 800)
        w, h = min(max(w, 900), sw), min(max(h, 560), sh)
        x, y = (int(m.group(3)), int(m.group(4))) if m and m.group(3) else ((sw - w) // 2, (sh - h) // 2)
        x, y = min(max(x, 0), max(sw - w, 0)), min(max(y, 0), max(sh - h, 0))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ── screens ───────────────────────────────────────────────────
    def show_connect(self):
        self.workspace.pack_forget()
        self.connect_screen.pack(fill="both", expand=True)
        self.connect_screen.on_show()
        self.status("Ready")

    def show_workspace(self):
        self.connect_screen.pack_forget()
        self.workspace.pack(fill="both", expand=True)
        self.workspace.on_show()

    def on_connected(self, db, info, password):
        if self.db and self.db is not db:
            self.db.close()
        self.db, self.conn_info, self.password = db, info, password
        self.log(f"Connected to {info.server} / {db.database}", "ok")
        self.show_workspace()

    # ── theme / log ───────────────────────────────────────────────
    @property
    def is_dark(self):
        return self.settings.theme == DARK_THEME

    def toggle_theme(self):
        self.settings.theme = DARK_THEME if self.dark_var.get() else LIGHT_THEME
        tb.Style().theme_use(self.settings.theme)
        self.apply_theme_colors()
        self.save_settings()

    def apply_theme_colors(self):
        c = tb.Style().colors
        self.log_text.configure(bg=c.inputbg, fg=c.fg, insertbackground=c.fg)
        self.workspace.apply_theme("dark" if self.is_dark else "light")

    def toggle_log(self):
        self.settings.show_log = self.log_var.get()
        panes = [str(p) for p in self.vpane.panes()]
        if self.settings.show_log and str(self.log_frame) not in panes:
            self.vpane.add(self.log_frame, weight=1)
        elif not self.settings.show_log and str(self.log_frame) in panes:
            self.vpane.forget(self.log_frame)
        self.save_settings()

    def log(self, msg, level="info"):
        t = self.log_text
        t.configure(state="normal")
        t.insert("end", time.strftime("%H:%M:%S "), "time")
        t.insert("end", f"{LOG_ICONS.get(level, '·')}  {msg}\n", level)
        t.see("end")
        t.configure(state="disabled")

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def status(self, msg):
        self.status_lbl.configure(text=msg)

    def toast(self, msg, style="success", duration=2200):
        try:
            tb.ToastNotification(APP_TITLE, msg, duration=duration, bootstyle=style).show_toast()
        except Exception:
            self.status(msg)

    # ── background jobs ───────────────────────────────────────────
    def register_busy(self, *widgets):
        """Widgets disabled while a background job runs."""
        self._busy_widgets.extend(widgets)

    @property
    def busy(self):
        return self.job is not None

    def run(self, fn, on_ok=None, label="Working…", on_err=None, on_progress=None,
            cancellable=False, on_done=None):
        if self.busy:
            self.toast("Another task is still running.", "warning")
            return None
        self.status(label)
        self._set_busy(True, cancellable)

        # Busy state is cleared *before* user callbacks so they can start a follow-up job.
        this = {}

        def finish():
            if self.job is not None and self.job is this.get("job"):
                self.job = None
                self._set_busy(False, False)

        def ok(result):
            finish()
            if on_ok:
                on_ok(result)

        def done(kind):
            finish()
            if kind == "cancelled":
                self.log("Cancelled.", "warn")
                self.status("Cancelled")
            if on_done:
                on_done(kind)

        def err(e):
            finish()
            self.log(str(e), "err")
            self.status(f"Error: {str(e).splitlines()[0][:120]}")
            if on_err:
                on_err(e)
            else:
                messagebox.showerror("Error", str(e), parent=self.root)

        self.job = run_bg(self.root, fn, on_ok=ok, on_err=err,
                          on_progress=on_progress, on_done=done)
        this["job"] = self.job
        return self.job

    def cancel_job(self):
        if self.job:
            self.job.cancel()
            self.status("Cancelling…")

    def _set_busy(self, busy, cancellable):
        for w in self._busy_widgets:
            try:
                w.configure(state="disabled" if busy else "normal")
            except tk.TclError:
                pass
        if busy:
            self.progress.pack(side="right", padx=(8, 0))
            self.progress.start(12)
            if cancellable:
                self.cancel_btn.pack(side="right")
            self.root.configure(cursor="watch")
        else:
            self.progress.stop()
            self.progress.pack_forget()
            self.cancel_btn.pack_forget()
            self.root.configure(cursor="")

    # ── dialogs ───────────────────────────────────────────────────
    def open_import(self):
        if not self.db:
            self.toast("Connect to a database first.", "warning")
            return
        from .ui.import_dialog import ImportDialog
        ImportDialog(self)

    def open_settings(self):
        from .ui.settings_dialog import SettingsDialog
        SettingsDialog(self)

    # ── persistence ───────────────────────────────────────────────
    def save_settings(self):
        try:
            self.settings.save()
        except OSError as e:
            self.log(f"Could not save settings: {e}", "warn")

    def _migrate_legacy(self):
        try:
            n = self.store.migrate_legacy()
        except Exception as e:
            self.log(f"Could not migrate v3 connections: {e}", "warn")
            return
        if n:
            self.log(f"Migrated {n} saved connection(s) from v3; passwords moved to "
                     "Windows Credential Manager (old file renamed to conn_details.pkl.bak).", "ok")
            self.connect_screen.reload()

    def quit(self):
        if self.job:
            self.job.cancel()
        self.settings.geometry = self.root.geometry()
        self.save_settings()
        if self.db:
            self.db.close()
        self.root.destroy()

    def mainloop(self):
        self.root.mainloop()


def main():
    App().mainloop()
