"""Import Excel / CSV files: build a plan, preview, then run in the background."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as tb

from .. import importer as imp
from ..metadata import get_table_columns
from ..worker import Cancelled, run_bg

PREVIEW_ROWS = 50
STATUS_STYLE = {"ready": "", "error": "err", "done": "ok", "running": "run", "cancelled": "warn",
                "failed": "err"}


class ImportDialog(tb.Toplevel):
    def __init__(self, app):
        super().__init__(title=f"Import data → {app.db.database}", transient=app.root,
                         size=(1100, 700), minsize=(800, 500))
        self.app = app
        self.items = []
        self.running = False
        s = app.settings

        # ── toolbar ──────────────────────────────────────────────
        bar = tb.Frame(self, padding=(12, 10))
        bar.pack(fill="x")
        self.add_files_btn = tb.Button(bar, text="+ Files…", bootstyle="primary-outline",
                                       command=self.add_files)
        self.add_files_btn.pack(side="left")
        self.add_folder_btn = tb.Button(bar, text="+ Folder…", bootstyle="primary-outline",
                                        command=self.add_folder)
        self.add_folder_btn.pack(side="left", padx=6)
        self.remove_btn = tb.Button(bar, text="Remove", bootstyle="secondary-outline",
                                    command=self.remove_selected)
        self.remove_btn.pack(side="left")
        self.clear_btn = tb.Button(bar, text="Clear", bootstyle="secondary-link", command=self.clear)
        self.clear_btn.pack(side="left", padx=4)

        self.mode_var = tk.StringVar(value=imp.MODES.get(s.import_default_mode, imp.MODES["create_append"]))
        self.schema_var = tk.StringVar(value=s.import_schema)
        self.apply_btn = tb.Button(bar, text="Apply to selected", bootstyle="secondary-outline",
                                   command=self.apply_to_selected)
        self.apply_btn.pack(side="right")
        tb.Combobox(bar, textvariable=self.mode_var, values=list(imp.MODES.values()),
                    state="readonly", width=28).pack(side="right", padx=6)
        tb.Label(bar, text="Mode").pack(side="right")
        tb.Entry(bar, textvariable=self.schema_var, width=10).pack(side="right", padx=(4, 14))
        tb.Label(bar, text="Schema").pack(side="right")

        # ── plan grid + preview ──────────────────────────────────
        pane = tb.Panedwindow(self, orient="vertical")
        pane.pack(fill="both", expand=True, padx=12)

        top = tb.Frame(pane)
        pane.add(top, weight=3)
        top.columnconfigure(0, weight=1)
        top.rowconfigure(0, weight=1)
        cols = ("file", "sheet", "target", "mode", "rows", "status")
        self.tree = tb.Treeview(top, columns=cols, show="headings", selectmode="extended")
        for c, text, w, anchor in [("file", "File", 220, "w"), ("sheet", "Sheet", 110, "w"),
                                   ("target", "Target table", 220, "w"), ("mode", "Mode", 190, "w"),
                                   ("rows", "Rows", 70, "e"), ("status", "Status", 260, "w")]:
            self.tree.heading(c, text=text, anchor=anchor)
            self.tree.column(c, width=w, anchor=anchor, stretch=c in ("file", "status"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = tb.Scrollbar(top, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.tag_configure("err", foreground="#e35d6a")
        self.tree.tag_configure("ok", foreground="#479f76")
        self.tree.tag_configure("warn", foreground="#e0a800")
        self.tree.tag_configure("run", foreground="#3dd5f3")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Delete>", lambda e: self.remove_selected())

        edit = tb.Frame(top)
        edit.grid(row=1, column=0, columnspan=2, sticky="ew", pady=6)
        tb.Label(edit, text="Target table").pack(side="left")
        self.target_var = tk.StringVar()
        self.target_entry = tb.Entry(edit, textvariable=self.target_var, width=40)
        self.target_entry.pack(side="left", padx=6)
        self.target_entry.bind("<Return>", lambda e: self.rename_target())
        self.rename_btn = tb.Button(edit, text="Set", bootstyle="secondary-outline",
                                    command=self.rename_target)
        self.rename_btn.pack(side="left")
        tb.Label(edit, text="Select a row to preview · schema.table or table",
                 bootstyle="secondary", font=("Segoe UI", 8)).pack(side="left", padx=10)

        bottom = tb.Frame(pane)
        pane.add(bottom, weight=2)
        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(1, weight=1)
        self.check_lbl = tb.Label(bottom, text="Preview", font=("Segoe UI", 9, "bold"))
        self.check_lbl.grid(row=0, column=0, sticky="w", pady=(4, 4))
        self.preview = tb.Treeview(bottom, show="headings", height=8)
        self.preview.grid(row=1, column=0, sticky="nsew")
        pv = tb.Scrollbar(bottom, orient="vertical", command=self.preview.yview)
        ph = tb.Scrollbar(bottom, orient="horizontal", command=self.preview.xview)
        pv.grid(row=1, column=1, sticky="ns")
        ph.grid(row=2, column=0, sticky="ew")
        self.preview.configure(yscrollcommand=pv.set, xscrollcommand=ph.set)

        # ── footer ───────────────────────────────────────────────
        foot = tb.Frame(self, padding=(12, 10))
        foot.pack(fill="x")
        self.summary = tb.Label(foot, text="Add files or a folder to begin.", bootstyle="secondary")
        self.summary.pack(side="left")
        self.close_btn = tb.Button(foot, text="Close", bootstyle="secondary-outline", command=self.close)
        self.close_btn.pack(side="right")
        self.cancel_btn = tb.Button(foot, text="Cancel", bootstyle="danger-outline",
                                    command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="right", padx=6)
        self.run_btn = tb.Button(foot, text="▶ Run import", bootstyle="success", command=self.run)
        self.run_btn.pack(side="right")
        self.bar = tb.Progressbar(foot, length=260, mode="determinate", bootstyle="success-striped")
        self.bar.pack(side="right", padx=12)

        self._edit_widgets = [self.add_files_btn, self.add_folder_btn, self.remove_btn,
                              self.clear_btn, self.apply_btn, self.rename_btn, self.run_btn]
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda e: self.close())

    # ── plan building ────────────────────────────────────────────
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select Excel / CSV files", parent=self,
            filetypes=[("Excel / CSV", "*.xlsx *.xlsm *.xls *.csv"), ("All files", "*.*")])
        if paths:
            self._add_paths(list(paths))

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select folder with Excel / CSV files", parent=self)
        if not folder:
            return
        paths = imp.discover(folder)
        if not paths:
            messagebox.showerror("No files", f"No Excel / CSV files found in:\n{folder}", parent=self)
            return
        self._add_paths(paths)

    def _add_paths(self, paths):
        known = {(i.path, i.sheet) for i in self.items}
        schema = self.schema_var.get().strip() or "dbo"
        mode = self._mode_key()

        def work(job):
            return imp.build_plan(paths, schema=schema, mode=mode, job=job,
                                  on_item=lambda it: job.progress(it))

        def progress(item):
            if self.winfo_exists():
                self.summary.configure(text=f"Reading {item.file}{' / ' + str(item.sheet) if item.sheet else ''}…")

        def ok(new_items):
            if not self.winfo_exists():
                return
            added = [i for i in new_items if (i.path, i.sheet) not in known]
            self.items += added
            self._render()
            self.app.log(f"Import: added {len(added)} item(s) from {len(paths)} file(s)", "info")

        self.app.run(work, ok, label="Reading files…", on_progress=progress, cancellable=True)

    def _mode_key(self):
        inv = {v: k for k, v in imp.MODES.items()}
        return inv.get(self.mode_var.get(), "create_append")

    def _render(self):
        sel = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for idx, it in enumerate(self.items):
            self._insert_row(idx, it)
        keep = [i for i in sel if self.tree.exists(i)]
        if keep:
            self.tree.selection_set(keep)
        self._update_summary()

    def _row_values(self, it):
        status = it.status if not it.error else f"{it.status}: {it.error}"
        return (it.file, "" if it.sheet is None else it.sheet, it.target, imp.MODES[it.mode],
                "" if it.rows is None else f"{it.rows:,}", status)

    def _insert_row(self, idx, it):
        self.tree.insert("", "end", iid=str(idx), values=self._row_values(it),
                         tags=(STATUS_STYLE.get(it.status, ""),))

    def _refresh_row(self, idx):
        it = self.items[idx]
        if self.tree.exists(str(idx)):
            self.tree.item(str(idx), values=self._row_values(it),
                           tags=(STATUS_STYLE.get(it.status, ""),))

    def _update_summary(self):
        ready = [i for i in self.items if i.status == "ready"]
        rows = sum(i.rows or 0 for i in ready)
        errs = sum(1 for i in self.items if i.status == "error")
        self.summary.configure(
            text=f"{len(self.items)} item(s) · {len(ready)} ready · {rows:,} rows"
                 + (f" · {errs} with errors" if errs else ""))

    def selected_indexes(self):
        return [int(i) for i in self.tree.selection()]

    def remove_selected(self):
        if self.running:
            return
        drop = set(self.selected_indexes())
        self.items = [it for i, it in enumerate(self.items) if i not in drop]
        self._render()
        self._clear_preview()

    def clear(self):
        if self.running:
            return
        self.items = []
        self._render()
        self._clear_preview()

    def apply_to_selected(self):
        idxs = self.selected_indexes() or list(range(len(self.items)))
        schema = self.schema_var.get().strip() or "dbo"
        mode = self._mode_key()
        for i in idxs:
            it = self.items[i]
            it.schema, it.mode = schema, mode
            if it.status in ("done", "failed", "cancelled") and it.frame is not None:
                it.status, it.error = "ready", ""
            self._refresh_row(i)
        self._on_select()

    def rename_target(self):
        idxs = self.selected_indexes()
        text = self.target_var.get().strip()
        if len(idxs) != 1 or not text:
            self.app.toast("Select one row and enter a table name.", "warning")
            return
        it = self.items[idxs[0]]
        if "." in text:
            schema, table = text.split(".", 1)
            it.schema, it.table = schema.strip("[] ") or "dbo", table.strip("[] ")
        else:
            it.table = text.strip("[] ")
        self._refresh_row(idxs[0])
        self._on_select()

    # ── preview + column check ───────────────────────────────────
    def _clear_preview(self):
        self.preview.delete(*self.preview.get_children())
        self.preview.configure(columns=())
        self.check_lbl.configure(text="Preview", bootstyle="default")
        self.target_var.set("")

    def _on_select(self, _=None):
        idxs = self.selected_indexes()
        if len(idxs) != 1:
            self._clear_preview()
            return
        it = self.items[idxs[0]]
        self.target_var.set(it.target)
        self.preview.delete(*self.preview.get_children())
        if it.frame is None:
            self.preview.configure(columns=())
            self.check_lbl.configure(text=f"✗ {it.error or 'No data loaded'}", bootstyle="danger")
            return
        cols = list(it.frame.columns)
        self.preview.configure(columns=[f"c{i}" for i in range(len(cols))])
        for i, c in enumerate(cols):
            self.preview.heading(f"c{i}", text=c, anchor="w")
            self.preview.column(f"c{i}", width=max(80, min(220, 9 * len(c) + 20)), stretch=False)
        for row in it.frame.head(PREVIEW_ROWS).itertuples(index=False, name=None):
            self.preview.insert("", "end", values=[str(v) for v in row])
        self.check_lbl.configure(text=f"Preview — first {min(PREVIEW_ROWS, len(it.frame))} rows  ·  checking target…",
                                 bootstyle="default")
        if not self.running:
            self._check_columns(idxs[0], it)

    def _check_columns(self, idx, it):
        db = self.app.db
        schema, table, mode, file_cols = it.schema, it.table, it.mode, list(it.columns)

        def work(job):
            return get_table_columns(db, schema, table)

        def ok(existing):
            if self.selected_indexes() != [idx] or not self.winfo_exists():
                return
            head = f"Preview — first {min(PREVIEW_ROWS, it.rows or 0)} rows  ·  "
            if existing is None:
                if mode in ("append", "truncate"):
                    msg, style = f"✗ Table {it.target} does not exist (mode requires it)", "danger"
                else:
                    msg, style = f"New table {it.target} will be created ({len(file_cols)} NVARCHAR(MAX) columns)", "info"
            elif mode == "replace":
                msg, style = f"⚠ Table {it.target} exists and will be DROPPED and recreated", "warning"
            else:
                missing, extra = imp.column_check(existing, file_cols)
                if missing:
                    msg, style = f"✗ Not in table: {', '.join(missing)}", "danger"
                elif extra:
                    msg, style = f"✓ Columns match · table-only columns left NULL: {', '.join(extra)}", "success"
                else:
                    msg, style = f"✓ Columns match existing table {it.target}", "success"
            self.check_lbl.configure(text=head + msg, bootstyle=style)

        def err(e):
            if self.winfo_exists():
                self.check_lbl.configure(text=f"Could not check target: {e}", bootstyle="warning")

        run_bg(self, work, on_ok=ok, on_err=err)

    # ── run ──────────────────────────────────────────────────────
    def run(self):
        todo = [i for i, it in enumerate(self.items) if it.status == "ready"]
        if not todo:
            self.app.toast("Nothing ready to import.", "warning")
            return
        replace = [self.items[i].target for i in todo if self.items[i].mode == "replace"]
        msg = f"Import {len(todo)} item(s) into '{self.app.db.database}'?"
        if replace:
            msg += "\n\nThese tables will be DROPPED and recreated:\n" + "\n".join(replace[:15])
        if not messagebox.askyesno("Confirm import", msg, parent=self):
            return

        db = self.app.db
        total_rows = sum(self.items[i].rows or 0 for i in todo) or 1
        self.bar.configure(maximum=total_rows, value=0)
        self._set_running(True)
        state = {"base": 0}

        def work(job):
            ok = failed = rows = 0
            for n, idx in enumerate(todo, 1):
                it = self.items[idx]
                job.progress("start", idx, n, len(todo))
                try:
                    count = imp.run_item(db, it, job,
                                         on_progress=lambda d, t, idx=idx: job.progress("rows", idx, d, t))
                    ok += 1
                    rows += count
                    job.progress("ok", idx, count)
                except Cancelled:
                    job.progress("cancelled", idx)
                    raise
                except Exception as e:
                    failed += 1
                    job.progress("failed", idx, str(e))
            return ok, failed, rows

        def progress(kind, idx, *args):
            if not self.winfo_exists():
                return
            it = self.items[idx]
            if kind == "start":
                n, total = args
                it.status, it.error = "running", ""
                self.app.status(f"Importing [{n}/{total}] {it.file} → {it.target}")
            elif kind == "rows":
                done, _ = args
                self.bar.configure(value=state["base"] + done)
            elif kind == "ok":
                it.status, it.error = "done", f"{args[0]:,} rows"
                state["base"] += it.rows or 0
                self.bar.configure(value=state["base"])
                self.app.log(f"{it.file} → [{it.target}] {args[0]:,} rows", "ok")
            elif kind == "failed":
                it.status, it.error = "failed", args[0]
                state["base"] += it.rows or 0
                self.app.log(f"{it.file} → [{it.target}] {args[0]}", "err")
            elif kind == "cancelled":
                it.status, it.error = "cancelled", "rolled back"
            self._refresh_row(idx)

        def ok(result):
            n_ok, n_failed, rows = result
            if not self.winfo_exists():
                return
            msg = f"Import finished: {n_ok} succeeded, {n_failed} failed, {rows:,} rows"
            self.app.log(msg, "warn" if n_failed else "ok")
            self.app.status(msg)
            self.summary.configure(text=msg)
            (messagebox.showwarning if n_failed else messagebox.showinfo)("Import finished", msg, parent=self)

        def done(kind):
            if self.winfo_exists():
                self._set_running(False)
            self.app.workspace.refresh_objects()

        self.app.run(work, ok, label="Importing…", on_progress=progress, cancellable=True,
                     on_done=done)

    def cancel(self):
        self.app.cancel_job()

    def _set_running(self, running):
        self.running = running
        for w in self._edit_widgets:
            w.configure(state="disabled" if running else "normal")
        self.cancel_btn.configure(state="normal" if running else "disabled")

    def close(self):
        if self.running:
            if not messagebox.askyesno("Import running",
                                       "An import is running. Cancel it and close?", parent=self):
                return
            self.app.cancel_job()
        self.destroy()
