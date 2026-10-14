"""Screen 2: object browser + script editor."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as tb

from .. import metadata as md
from ..scripting import (ScriptOptions, build_module_script, build_table_script, compact,
                         order_objects, safe_filename)
from .sql_text import SqlText

HEADER_MODES = {
    "drop_create":     "DROP + CREATE",
    "create_or_alter": "CREATE OR ALTER",
    "definition":      "Definition only",
}
CATEGORY_ICONS = {"Tables": "▦", "Views": "◫", "Procedures": "⚙", "Functions": "ƒ", "Triggers": "⚡"}
CHIP_LABELS = {"Tables": "Tables", "Views": "Views", "Procedures": "Procs", "Functions": "Funcs", "Triggers": "Trig"}


class WorkspaceScreen(tb.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.objects = []
        self.by_id = {}
        self.last_scripts = []          # [(ObjectInfo, script)] from the last Generate
        self.last_text = ""
        self._filter_after = None

        self._build_topbar()
        self.hpane = tb.Panedwindow(self, orient="horizontal")
        self.hpane.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self._build_browser()
        self._build_editor()
        self._bind_keys()

    # ── top bar ───────────────────────────────────────────────────
    def _build_topbar(self):
        bar = tb.Frame(self, padding=(10, 8))
        bar.pack(fill="x")
        self.back_btn = tb.Button(bar, text="← Connections", bootstyle="secondary-outline",
                                  command=self.app.show_connect)
        self.back_btn.pack(side="left")
        self.badge = tb.Label(bar, text="", bootstyle="inverse-primary", padding=(10, 4),
                              font=("Segoe UI", 9, "bold"))
        self.badge.pack(side="left", padx=10)
        tb.Label(bar, text="Database").pack(side="left", padx=(10, 4))
        self.db_var = tk.StringVar()
        self.db_combo = tb.Combobox(bar, textvariable=self.db_var, state="readonly", width=28)
        self.db_combo.pack(side="left")
        self.db_combo.bind("<<ComboboxSelected>>", self._switch_db)

        self.settings_btn = tb.Button(bar, text="⚙ Settings", bootstyle="secondary-link",
                                      command=self.app.open_settings)
        self.settings_btn.pack(side="right")
        self.import_btn = tb.Button(bar, text="📂 Import data…", bootstyle="success-outline",
                                    command=self.app.open_import)
        self.import_btn.pack(side="right", padx=6)
        self.app.register_busy(self.back_btn, self.db_combo, self.import_btn)

    # ── object browser ────────────────────────────────────────────
    def _build_browser(self):
        box = tb.Frame(self.hpane, padding=(0, 0, 8, 0))
        self.hpane.add(box, weight=1)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(3, weight=1)

        top = tb.Frame(box)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        tb.Label(top, text="OBJECTS", font=("Segoe UI", 9, "bold"), bootstyle="secondary").pack(side="left")
        self.count_lbl = tb.Label(top, text="", bootstyle="secondary", font=("Segoe UI", 8))
        self.count_lbl.pack(side="left", padx=6)
        self.refresh_btn = tb.Button(top, text="⟳", bootstyle="secondary-link", padding=(4, 0),
                                     command=self.refresh_objects)
        self.refresh_btn.pack(side="right")

        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._schedule_filter())
        self.filter_entry = tb.Entry(box, textvariable=self.filter_var)
        self.filter_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 4))
        self.filter_entry.bind("<Return>", lambda e: self._filter_enter())
        self.filter_entry.bind("<Down>", lambda e: self._focus_tree())

        chips = tb.Frame(box)
        chips.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.type_vars = {}
        for cat in md.CATEGORIES:
            var = tk.BooleanVar(value=True)
            self.type_vars[cat] = var
            tb.Checkbutton(chips, text=CHIP_LABELS[cat],
                           variable=var, bootstyle="info-outline-toolbutton",
                           command=self.apply_filter, padding=(5, 1)).pack(side="left", padx=(0, 2))

        self.tree = tb.Treeview(box, show="tree", selectmode="extended")
        self.tree.column("#0", width=280)
        self.tree.grid(row=3, column=0, sticky="nsew")
        sb = tb.Scrollbar(box, orient="vertical", command=self.tree.yview)
        sb.grid(row=3, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Return>", lambda e: self.generate())
        self.tree.bind("<Button-3>", self._context_menu)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_sel_label())

        self.sel_lbl = tb.Label(box, text="", bootstyle="secondary", font=("Segoe UI", 8))
        self.sel_lbl.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="Generate script", command=self.generate)
        self.menu.add_command(label="Script data (INSERT)…", command=self._script_data_selected)
        self.menu.add_command(label="Copy name(s)", command=self._copy_names)
        self.menu.add_separator()
        self.menu.add_command(label="Select all in group", command=self._select_group)

    # ── editor ────────────────────────────────────────────────────
    def _build_editor(self):
        box = tb.Frame(self.hpane, padding=(8, 0, 0, 0))
        self.hpane.add(box, weight=3)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(2, weight=1)
        s = self.app.settings

        tools = tb.Frame(box)
        tools.grid(row=0, column=0, sticky="ew")
        self.gen_btn = tb.Button(tools, text="⚙ Generate", bootstyle="primary", command=self.generate)
        self.gen_btn.pack(side="left")
        self.copy_btn = tb.Button(tools, text="📋 Copy", bootstyle="secondary-outline",
                                  command=self.copy_script)
        self.copy_btn.pack(side="left", padx=(6, 0))
        self.save_btn = tb.Button(tools, text="💾 Save .sql", bootstyle="secondary-outline",
                                  command=self.save_script)
        self.save_btn.pack(side="left", padx=(6, 0))
        tb.Button(tools, text="Clear", bootstyle="secondary-link",
                  command=self.clear_script).pack(side="left", padx=(6, 0))
        self.data_btn = tb.Button(tools, text="⇩ Data → INSERT", bootstyle="info-outline",
                                  command=self.open_data_script)
        self.data_btn.pack(side="left", padx=(12, 0))
        self.app.register_busy(self.gen_btn, self.refresh_btn, self.data_btn)

        tb.Label(tools, text="Ctrl+Enter generate · Ctrl+Shift+C copy · Ctrl+S save · Ctrl+Shift+D data",
                 bootstyle="secondary", font=("Segoe UI", 8)).pack(side="right")

        opts = tb.Frame(box)
        opts.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        tb.Label(opts, text="Header").pack(side="left")
        self.mode_var = tk.StringVar(value=HEADER_MODES.get(s.header_mode, HEADER_MODES["drop_create"]))
        mode = tb.Combobox(opts, textvariable=self.mode_var, values=list(HEADER_MODES.values()),
                           state="readonly", width=18)
        mode.pack(side="left", padx=(4, 12))
        mode.bind("<<ComboboxSelected>>", lambda e: self._save_opts())

        self.opt_vars = {}
        for key, text in [("include_grants", "Grants"), ("include_separator", "Separator")]:
            var = tk.BooleanVar(value=getattr(s, key))
            self.opt_vars[key] = var
            tb.Checkbutton(opts, text=text, variable=var, bootstyle="round-toggle",
                           command=self._save_opts).pack(side="left", padx=(0, 12))

        tbl = tb.Menubutton(opts, text="Table options", bootstyle="secondary-outline")
        tbl.pack(side="left")
        tmenu = tk.Menu(tbl, tearoff=False)
        for key, text in [("table_if_not_exists", "Wrap in IF NOT EXISTS"),
                          ("varchar_to_nvarchar", "Convert VARCHAR → NVARCHAR"),
                          (None, None),
                          ("table_indexes", "Include indexes"),
                          ("table_foreign_keys", "Include foreign keys"),
                          ("table_check_constraints", "Include check constraints")]:
            if key is None:
                tmenu.add_separator()
                continue
            var = tk.BooleanVar(value=getattr(s, key))
            self.opt_vars[key] = var
            tmenu.add_checkbutton(label=text, variable=var, command=self._save_opts)
        tbl.configure(menu=tmenu)
        self.roles_lbl = tb.Label(opts, text="", bootstyle="secondary", font=("Segoe UI", 8))
        self.roles_lbl.pack(side="right")

        self.editor = SqlText(box)
        self.editor.grid(row=2, column=0, sticky="nsew")
        self.refresh_roles_label()

    def _bind_keys(self):
        r = self.app.root
        r.bind_all("<Control-Return>", lambda e: self._if_visible(self.generate))
        r.bind_all("<Control-Shift-C>", lambda e: self._if_visible(self.copy_script))
        r.bind_all("<Control-Shift-c>", lambda e: self._if_visible(self.copy_script))
        r.bind_all("<Control-s>", lambda e: self._if_visible(self.save_script))
        r.bind_all("<Control-f>", lambda e: self._if_visible(self._focus_filter))
        r.bind_all("<F5>", lambda e: self._if_visible(self.refresh_objects))
        r.bind_all("<Control-Shift-D>", lambda e: self._if_visible(self.open_data_script))
        r.bind_all("<Control-Shift-d>", lambda e: self._if_visible(self.open_data_script))

    def _if_visible(self, fn):
        if self.winfo_ismapped():
            fn()
            return "break"

    # ── lifecycle ─────────────────────────────────────────────────
    def on_show(self):
        db, info = self.app.db, self.app.conn_info
        self.badge.configure(text=f"{info.alias or info.server}  ›  {db.database}")
        self.app.status(f"Connected to {info.server} / {db.database}")
        self.db_var.set(db.database)
        self.refresh_roles_label()
        self.refresh_objects(load_dbs=True)
        self.filter_entry.focus_set()

    def apply_theme(self, mode):
        self.editor.set_palette(mode)

    def refresh_roles_label(self):
        roles = ", ".join(self.app.settings.grant_roles) or "none"
        self.roles_lbl.configure(text=f"Grant roles: {roles}")

    def _switch_db(self, _=None):
        name = self.db_var.get()
        db = self.app.db
        if not name or name == db.database:
            return

        def work(job):
            db.use(name)
            return name

        def ok(_):
            self.app.log(f"Switched to database {name}", "ok")
            info = self.app.conn_info
            self.badge.configure(text=f"{info.alias or info.server}  ›  {name}")
            self.app.status(f"Connected to {info.server} / {name}")
            self.last_scripts = []
            self.refresh_objects()

        def err(e):
            self.db_var.set(db.database)
            messagebox.showerror("Switch database", str(e), parent=self)

        self.app.run(work, ok, label=f"Switching to {name}…", on_err=err)

    def refresh_objects(self, load_dbs=False):
        db = self.app.db
        if db is None or not self.winfo_exists():
            return

        def work(job):
            dbs = db.list_databases() if load_dbs else None
            return md.list_objects(db), dbs

        def ok(result):
            objects, dbs = result
            if dbs is not None:
                self.db_combo.configure(values=dbs)
            self.objects = objects
            self.by_id = {o.object_id: o for o in objects}
            self.apply_filter()
            self.app.log(f"Loaded {len(objects)} objects from {db.database}", "info")
            self.app.status(f"{len(objects)} objects in {db.database}")

        self.app.run(work, ok, label=f"Loading objects from {db.database}…")

    # ── filtering ─────────────────────────────────────────────────
    def _schedule_filter(self):
        if self._filter_after:
            self.after_cancel(self._filter_after)
        self._filter_after = self.after(120, self.apply_filter)

    def apply_filter(self):
        self._filter_after = None
        text = self.filter_var.get().strip().lower()
        terms = text.split()
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        groups = {}
        shown = 0
        for o in self.objects:
            cat = o.category
            if cat not in self.type_vars or not self.type_vars[cat].get():
                continue
            hay = o.full_name.lower()
            if terms and not all(t in hay for t in terms):
                continue
            groups.setdefault(cat, []).append(o)
        for cat in md.CATEGORIES:
            items = groups.get(cat)
            if not items:
                continue
            gid = f"cat:{cat}"
            self.tree.insert("", "end", iid=gid, text=f"{CATEGORY_ICONS[cat]}  {cat}  ({len(items)})",
                             open=bool(terms) or len(items) <= 200)
            for o in items:
                iid = str(o.object_id)
                self.tree.insert(gid, "end", iid=iid, text=o.full_name)
                shown += 1
        keep = [i for i in selected if self.tree.exists(i)]
        if keep:
            self.tree.selection_set(keep)
        self.count_lbl.configure(text=f"{shown} of {len(self.objects)}" if shown != len(self.objects)
                                 else f"{len(self.objects)}")
        self._update_sel_label()

    def _filter_enter(self):
        """Enter in the filter: exact name match generates it, otherwise focus the first hit."""
        text = self.filter_var.get().strip()
        if not text:
            return
        low = text.lower().replace("[", "").replace("]", "")
        exact = [o for o in self.objects if low in (o.name.lower(), o.full_name.lower())]
        if len(exact) == 1:
            self.tree.selection_set(str(exact[0].object_id))
            self.tree.see(str(exact[0].object_id))
            self.generate()
        else:
            self._focus_tree()

    def _focus_tree(self):
        first = self._first_leaf()
        if first:
            self.tree.focus_set()
            self.tree.focus(first)
            self.tree.selection_set(first)
            self.tree.see(first)
        return "break"

    def _focus_filter(self):
        self.filter_entry.focus_set()
        self.filter_entry.select_range(0, "end")

    def _first_leaf(self):
        for g in self.tree.get_children():
            kids = self.tree.get_children(g)
            if kids:
                return kids[0]
        return None

    # ── selection helpers ─────────────────────────────────────────
    def selected_objects(self):
        out = []
        for iid in self.tree.selection():
            if iid.startswith("cat:"):
                out += [self.by_id[int(k)] for k in self.tree.get_children(iid)]
            else:
                out.append(self.by_id[int(iid)])
        seen = set()
        return [o for o in out if not (o.object_id in seen or seen.add(o.object_id))]

    def _update_sel_label(self):
        n = len(self.selected_objects()) if self.objects else 0
        self.sel_lbl.configure(text=f"{n} selected" if n else "Select objects · Ctrl/Shift for multiple")

    def _on_double(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and not iid.startswith("cat:"):
            self.tree.selection_set(iid)
            self.generate()
            return "break"

    def _context_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        if self.tree.selection():
            self.menu.tk_popup(event.x_root, event.y_root)

    def _copy_names(self):
        names = "\n".join(o.full_name for o in self.selected_objects())
        if names:
            self.clipboard_clear()
            self.clipboard_append(names)
            self.app.status("Copied object names")

    # ── data → INSERT ─────────────────────────────────────────────
    def open_data_script(self, sql=None, target=None):
        if self.app.busy:
            self.app.toast("Another task is still running.", "warning")
            return
        from .data_script_dialog import DataScriptDialog
        DataScriptDialog(self.app, sql=sql, target=target)

    def _script_data_selected(self):
        tables = [o for o in self.selected_objects() if o.type == "U"]
        if not tables:
            self.app.toast("Select a table to script its data.", "warning")
            return
        from ..datascript import select_all_sql, table_text
        t = tables[0]
        self.open_data_script(select_all_sql(t.schema, t.name), table_text(t.schema, t.name))

    def _select_group(self):
        sel = self.tree.selection()
        if sel:
            parent = sel[0] if sel[0].startswith("cat:") else self.tree.parent(sel[0])
            self.tree.selection_set(self.tree.get_children(parent))

    # ── options ───────────────────────────────────────────────────
    def _save_opts(self):
        s = self.app.settings
        inv = {v: k for k, v in HEADER_MODES.items()}
        s.header_mode = inv.get(self.mode_var.get(), "drop_create")
        for k, var in self.opt_vars.items():
            setattr(s, k, var.get())
        self.app.save_settings()

    def script_options(self):
        self._save_opts()
        return ScriptOptions.from_settings(self.app.settings)

    # ── generate ──────────────────────────────────────────────────
    def generate(self, objs=None):
        objs = objs or self.selected_objects()
        if not objs:
            text = self.filter_var.get().strip()
            if text:
                return self._generate_by_name(text)
            self.app.toast("Select one or more objects (or type a name in the filter).", "warning")
            return
        opts = self.script_options()
        db = self.app.db

        def work(job):
            edges = md.get_dependencies(db, [o.object_id for o in objs]) if len(objs) > 1 else []
            ordered = order_objects(objs, edges)
            scripts, fk_parts, errors = [], [], []
            for i, o in enumerate(ordered, 1):
                job.check()
                job.progress(i, len(ordered), o)
                try:
                    if o.type == "U":
                        meta = md.get_table_meta(db, o)
                        script, fks = build_table_script(meta, opts, separate_fks=True)
                        if fks:
                            fk_parts.append((o, fks))
                    else:
                        script = build_module_script(o, md.get_definition(db, o.object_id), opts)
                    scripts.append((o, script))
                except Exception as e:
                    errors.append((o, str(e)))
            return scripts, fk_parts, errors

        def progress(i, n, o):
            self.app.status(f"Scripting [{i}/{n}] {o.full_name}…")

        def ok(result):
            scripts, fk_parts, errors = result
            parts = [s for _, s in scripts]
            if fk_parts:
                fk_text = "\n".join(f for _, f in fk_parts)
                if len(scripts) == 1:
                    parts[0] = _insert_before_separator(parts[0], fk_text, opts.include_separator)
                else:
                    parts.append("-- Foreign keys\n" + fk_text)
                # keep per-object files complete: append each table's FKs to its own file
                fk_map = {o.object_id: f for o, f in fk_parts}
                scripts = [(o, _insert_before_separator(s, fk_map[o.object_id], opts.include_separator)
                            if o.object_id in fk_map else s) for o, s in scripts]
            text = "\n".join(parts)
            self.editor.set(text)
            self.last_scripts, self.last_text = scripts, text
            for o, e in errors:
                self.app.log(f"{o.full_name}: {e}", "err")
            if len(scripts) == 1:
                o = scripts[0][0]
                msg = f"Script generated for [{o.type}] {o.full_name}"
            else:
                msg = f"Generated {len(scripts)} scripts" + (f", {len(errors)} failed" if errors else "")
            self.app.status(msg)
            self.app.log(msg, "warn" if errors else "ok")
            if errors and not scripts:
                messagebox.showerror("Generate", "\n".join(f"{o.full_name}: {e}" for o, e in errors[:10]),
                                     parent=self)

        self.app.run(work, ok, label="Generating…", on_progress=progress, cancellable=len(objs) > 3)

    def _generate_by_name(self, text):
        db = self.app.db

        def work(job):
            return md.resolve_object(db, text)

        def ok(found):
            if not found:
                self.app.status(f"'{text}' not found")
                messagebox.showerror("Not found", f"'{text}' not found in '{db.database}'.", parent=self)
                return
            if len(found) > 1 and found[0].schema != "dbo":
                self.app.log(f"'{text}' exists in several schemas; using {found[0].full_name}", "warn")
            o = found[0]
            if o.object_id not in self.by_id:
                self.by_id[o.object_id] = o
                self.objects.append(o)
                self.apply_filter()
            if self.tree.exists(str(o.object_id)):
                self.tree.selection_set(str(o.object_id))
                self.tree.see(str(o.object_id))
            self.generate([o])

        self.app.run(work, ok, label=f"Looking up {text}…")

    # ── copy / save / clear ───────────────────────────────────────
    def copy_script(self):
        script = self.editor.get().strip()
        if not script:
            self.app.toast("Nothing to copy.", "warning")
            return
        if self.app.settings.compact_copy:
            script = compact(script)
        self.clipboard_clear()
        self.clipboard_append(script)
        self.app.status("Copied to clipboard")
        self.app.toast("Script copied to clipboard")

    def save_script(self):
        text = self.editor.get()
        if not text.strip():
            self.app.toast("Nothing to save.", "warning")
            return
        per_object = False
        if len(self.last_scripts) > 1 and text == self.last_text:
            ans = messagebox.askyesnocancel(
                "Save scripts",
                f"Save {len(self.last_scripts)} scripts as one file per object?\n\n"
                "Yes = one file per object (pick a folder)\nNo = one combined file", parent=self)
            if ans is None:
                return
            per_object = ans
        try:
            if per_object:
                folder = filedialog.askdirectory(title="Folder for .sql files", parent=self)
                if not folder:
                    return
                for o, script in self.last_scripts:
                    path = os.path.join(folder, safe_filename(f"{o.schema}.{o.name}") + ".sql")
                    _write_sql(path, script)
                msg = f"Saved {len(self.last_scripts)} files to {folder}"
            else:
                default = (safe_filename(self.last_scripts[0][0].full_name) if len(self.last_scripts) == 1
                           else safe_filename(self.app.db.database + "_scripts"))
                path = filedialog.asksaveasfilename(
                    title="Save script", defaultextension=".sql", initialfile=default + ".sql",
                    filetypes=[("SQL script", "*.sql"), ("All files", "*.*")], parent=self)
                if not path:
                    return
                _write_sql(path, text)
                msg = f"Saved {path}"
        except OSError as e:
            messagebox.showerror("Save", str(e), parent=self)
            return
        self.app.log(msg, "ok")
        self.app.status(msg)
        self.app.toast(msg)

    def clear_script(self):
        self.editor.clear()
        self.last_scripts, self.last_text = [], ""


def _write_sql(path, text):
    # UTF-8 with BOM so SSMS detects the encoding; CRLF line endings for Windows tools
    with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(text if text.endswith("\n") else text + "\n")


def _insert_before_separator(script, extra, has_separator):
    if has_separator:
        head, sep, tail = script.rpartition("\n")
        return f"{head}\n{extra}\n{tail}"
    return f"{script}\n{extra}"
