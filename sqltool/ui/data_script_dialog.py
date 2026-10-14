"""Data → INSERT: run a SELECT and script the rows as INSERT statements."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as tb

from .. import datascript as ds
from .sql_text import SqlText


class DataScriptDialog(tb.Toplevel):
    last_sql = ""                       # remembered for the session

    def __init__(self, app, sql=None, target=None):
        super().__init__(title=f"Data → INSERT  ·  {app.db.database}", transient=app.root,
                         size=(860, 520), minsize=(640, 420))
        self.app = app
        self._auto_target = target is None
        body = tb.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        tb.Label(body, text="SELECT query", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        tb.Label(body, text="Each returned row becomes one INSERT statement. Only SELECT is allowed.",
                 bootstyle="secondary", font=("Segoe UI", 8)).grid(row=0, column=1, sticky="e")
        self.sql = SqlText(body)
        self.sql.text.configure(height=8)
        self.sql.set_palette("dark" if app.is_dark else "light")
        self.sql.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(4, 10))
        self.sql.set(sql if sql is not None else (DataScriptDialog.last_sql or "SELECT * FROM "))
        self.sql.text.mark_set("insert", "end-1c")
        self.sql.text.bind("<KeyRelease>", lambda e: self._update_target())

        tb.Label(body, text="Target table").grid(row=2, column=0, sticky="w", padx=(0, 10))
        self.target_var = tk.StringVar(value=target or "")
        te = tb.Entry(body, textvariable=self.target_var)
        te.grid(row=2, column=1, sticky="ew")
        te.bind("<Key>", lambda e: setattr(self, "_auto_target", False))
        self.hint = tb.Label(body, text="", font=("Segoe UI", 8))
        self.hint.grid(row=3, column=1, sticky="w", pady=(2, 0))

        opts = tb.Frame(body)
        opts.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.identity_var = tk.BooleanVar(value=True)
        tb.Checkbutton(opts, text="SET IDENTITY_INSERT ON/OFF when an identity column is included",
                       variable=self.identity_var, bootstyle="round-toggle").pack(side="left")
        out = tb.Frame(body)
        out.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        tb.Label(out, text="Output").pack(side="left", padx=(0, 10))
        self.output_var = tk.StringVar(value="editor")
        tb.Radiobutton(out, text=f"Editor (up to {ds.EDITOR_ROW_LIMIT:,} rows)", value="editor",
                       variable=self.output_var).pack(side="left")
        tb.Radiobutton(out, text="File… (any number of rows)", value="file",
                       variable=self.output_var).pack(side="left", padx=14)

        btns = tb.Frame(body)
        btns.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        tb.Label(btns, text="Ctrl+Enter to generate", bootstyle="secondary",
                 font=("Segoe UI", 8)).pack(side="left")
        tb.Button(btns, text="Close", bootstyle="secondary-outline", command=self.destroy).pack(side="right")
        self.gen_btn = tb.Button(btns, text="⚙ Generate INSERTs", bootstyle="primary", command=self.generate)
        self.gen_btn.pack(side="right", padx=6)

        for w in (self, self.sql.text):
            w.bind("<Control-Return>", lambda e: (self.generate(), "break")[1])
        self.bind("<Escape>", lambda e: self.destroy())
        self._update_target()
        self.sql.text.focus_set()

    def _update_target(self):
        target, needs_check = ds.guess_target(self.sql.get())
        if self._auto_target:
            self.target_var.set(target or "")
        if needs_check:
            self.hint.configure(text="⚠ Query has a join / subquery / CTE: check the target table and "
                                     "that every column belongs to it.", bootstyle="warning")
        else:
            self.hint.configure(text="Filled in from the FROM clause. Edit if needed.", bootstyle="secondary")

    def generate(self):
        sql = self.sql.get().strip()
        target = self.target_var.get().strip()
        try:
            ds.validate_select(sql)
        except ValueError as e:
            messagebox.showerror("Data → INSERT", str(e), parent=self)
            return
        if not target:
            messagebox.showerror("Data → INSERT", "Enter the target table.", parent=self)
            return
        DataScriptDialog.last_sql = sql
        to_file = self.output_var.get() == "file"
        path = None
        if to_file:
            name = target.replace("[", "").replace("]", "").split(".")[-1]
            path = filedialog.asksaveasfilename(
                title="Save INSERT script", defaultextension=".sql", initialfile=f"{name}_data.sql",
                filetypes=[("SQL script", "*.sql"), ("All files", "*.*")], parent=self)
            if not path:
                return
        db, wrap = self.app.db, self.identity_var.get()

        def work(job):
            if to_file:
                # UTF-8 with BOM + CRLF, like Save .sql; a partial file is removed on failure
                f = open(path, "w", encoding="utf-8-sig", newline="\r\n")
                try:
                    res = ds.script_rows(db, sql, target, lambda s: f.write(s + "\n"), job, wrap)
                except BaseException:
                    f.close()
                    os.remove(path)
                    raise
                f.close()
                return res
            lines = []
            res = ds.script_rows(db, sql, target, lines.append, job, wrap, limit=ds.EDITOR_ROW_LIMIT)
            res.text = "\n".join(lines)
            return res

        def progress(rows):
            self.app.status(f"Scripting data… {rows:,} rows")

        def ok(res):
            for w in res.warnings:
                self.app.log(w, "warn")
            if res.skipped:
                self.app.log("Skipped (computed / rowversion): " + ", ".join(res.skipped), "info")
            if not res.rows:
                self.app.status("No rows returned")
                if self.winfo_exists():
                    messagebox.showinfo("Data → INSERT", "The query returned no rows.", parent=self)
                return
            where = f" to {path}" if to_file else ""
            msg = f"Scripted {res.rows:,} row(s) from {target}{where}"
            if to_file:
                self.app.toast(msg)
            else:
                ws = self.app.workspace
                ws.editor.set(res.text)
                ws.last_scripts, ws.last_text = [], res.text
            self.app.log(msg, "ok")
            self.app.status(msg)
            if self.winfo_exists():
                self.destroy()

        def err(e):
            if isinstance(e, ds.TooManyRows) and self.winfo_exists():
                if messagebox.askyesno("Too many rows", f"{e}\n\nSwitch output to File and generate now?",
                                       parent=self):
                    self.output_var.set("file")
                    self.after(10, self.generate)
            elif self.winfo_exists():
                messagebox.showerror("Data → INSERT", str(e), parent=self)

        self.app.run(work, ok, label="Scripting data…", on_err=err, on_progress=progress,
                     cancellable=True)
