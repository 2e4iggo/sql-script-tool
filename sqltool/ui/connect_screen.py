"""Screen 1: saved connections + connection form."""
import time
import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as tb

from ..connections import ConnInfo, get_password
from ..db import Database, available_drivers

AUTO_DRIVER = "(auto-detect)"


class ConnectScreen(tb.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=14)
        self.app = app
        self._items = {}
        self.columnconfigure(0, weight=3, uniform="c")
        self.columnconfigure(1, weight=2, uniform="c")
        self.rowconfigure(1, weight=1)

        hdr = tb.Frame(self)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        tb.Label(hdr, text="◈  SQL Script Tool", font=("Segoe UI", 16, "bold"),
                 bootstyle="primary").pack(side="left")
        tb.Label(hdr, text="Connect to SQL Server", font=("Segoe UI", 10),
                 bootstyle="secondary").pack(side="left", padx=12, pady=(6, 0))

        self._build_saved()
        self._build_form()

    # ── saved connections ─────────────────────────────────────────
    def _build_saved(self):
        box = tb.Labelframe(self, text=" Saved connections ", padding=10)
        box.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        box.rowconfigure(1, weight=1)
        box.columnconfigure(0, weight=1)

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.reload())
        sf = tb.Frame(box)
        sf.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        tb.Label(sf, text="🔍").pack(side="left", padx=(0, 6))
        tb.Entry(sf, textvariable=self.search_var).pack(side="left", fill="x", expand=True)

        cols = ("name", "database", "user", "used")
        self.tree = tb.Treeview(box, columns=cols, show="headings", selectmode="browse")
        for c, text, w in [("name", "Server / alias", 220), ("database", "Database", 160),
                           ("user", "Auth", 120), ("used", "Last used", 110)]:
            self.tree.heading(c, text=text, anchor="w")
            self.tree.column(c, width=w, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew")
        sb = tb.Scrollbar(box, orient="vertical", command=self.tree.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self.connect())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.tree.bind("<Return>", lambda e: self.connect())

        btns = tb.Frame(box)
        btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        tb.Button(btns, text="+ New", bootstyle="secondary-outline",
                  command=self.new_connection).pack(side="left")
        tb.Button(btns, text="Delete", bootstyle="danger-outline",
                  command=self.delete_selected).pack(side="left", padx=6)
        tb.Label(btns, text="Double-click to connect  ·  Del to remove",
                 bootstyle="secondary", font=("Segoe UI", 8)).pack(side="right")

    def reload(self):
        q = self.search_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        self._items.clear()
        for i, c in enumerate(self.app.store.sorted()):
            hay = f"{c.label} {c.server} {c.database} {c.username}".lower()
            if q and q not in hay:
                continue
            iid = str(i)
            self._items[iid] = c
            auth = "Windows" if c.auth == "windows" else c.username
            used = time.strftime("%Y-%m-%d", time.localtime(c.last_used)) if c.last_used else ""
            name = c.alias or c.server
            self.tree.insert("", "end", iid=iid, values=(name, c.database, auth, used))

    def _on_select(self, _=None):
        sel = self.tree.selection()
        if sel and sel[0] in self._items:
            self.fill_form(self._items[sel[0]])

    def delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        info = self._items[sel[0]]
        if messagebox.askyesno("Delete connection", f"Remove saved connection\n\n{info.label}?",
                               parent=self):
            self.app.store.delete(info)
            self.app.log(f"Removed {info.label}", "ok")
            self.reload()

    # ── form ──────────────────────────────────────────────────────
    def _build_form(self):
        box = tb.Labelframe(self, text=" Connection ", padding=14)
        box.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        box.columnconfigure(1, weight=1)

        self.v = {k: tk.StringVar() for k in ("alias", "server", "database", "user", "pwd", "driver")}
        self.auth_var = tk.StringVar(value="sql")
        self.encrypt_var = tk.BooleanVar(value=False)
        self.trust_var = tk.BooleanVar(value=True)
        self.show_pwd = tk.BooleanVar(value=False)

        r = 0

        def label(text):
            tb.Label(box, text=text, font=("Segoe UI", 9)).grid(row=r, column=0, sticky="w",
                                                                pady=5, padx=(0, 10))

        label("Server")
        self.server_entry = tb.Entry(box, textvariable=self.v["server"])
        self.server_entry.grid(row=r, column=1, columnspan=2, sticky="ew")
        r += 1

        label("Authentication")
        af = tb.Frame(box)
        af.grid(row=r, column=1, columnspan=2, sticky="w")
        tb.Radiobutton(af, text="SQL Server", value="sql", variable=self.auth_var,
                       command=self._auth_changed).pack(side="left")
        tb.Radiobutton(af, text="Windows", value="windows", variable=self.auth_var,
                       command=self._auth_changed).pack(side="left", padx=12)
        r += 1

        label("Username")
        self.user_entry = tb.Entry(box, textvariable=self.v["user"])
        self.user_entry.grid(row=r, column=1, columnspan=2, sticky="ew")
        r += 1

        label("Password")
        self.pwd_entry = tb.Entry(box, textvariable=self.v["pwd"], show="•")
        self.pwd_entry.grid(row=r, column=1, sticky="ew")
        self.show_btn = tb.Checkbutton(box, text="Show", variable=self.show_pwd,
                                       bootstyle="secondary-toolbutton",
                                       command=lambda: self.pwd_entry.configure(
                                           show="" if self.show_pwd.get() else "•"))
        self.show_btn.grid(row=r, column=2, padx=(6, 0))
        r += 1

        label("Database")
        self.db_combo = tb.Combobox(box, textvariable=self.v["database"])
        self.db_combo.grid(row=r, column=1, sticky="ew")
        self.load_btn = tb.Button(box, text="⟳ Load", bootstyle="secondary-outline",
                                  command=self.load_databases)
        self.load_btn.grid(row=r, column=2, padx=(6, 0))
        r += 1

        tb.Separator(box).grid(row=r, column=0, columnspan=3, sticky="ew", pady=10)
        r += 1

        label("Alias (optional)")
        tb.Entry(box, textvariable=self.v["alias"]).grid(row=r, column=1, columnspan=2, sticky="ew")
        r += 1

        label("Driver")
        drivers = [AUTO_DRIVER]
        try:
            drivers += available_drivers()
        except Exception:
            pass
        self.v["driver"].set(AUTO_DRIVER)
        tb.Combobox(box, textvariable=self.v["driver"], values=drivers, state="readonly").grid(
            row=r, column=1, columnspan=2, sticky="ew")
        r += 1

        of = tb.Frame(box)
        of.grid(row=r, column=1, columnspan=2, sticky="w", pady=(4, 0))
        tb.Checkbutton(of, text="Encrypt", variable=self.encrypt_var,
                       bootstyle="round-toggle").pack(side="left")
        tb.Checkbutton(of, text="Trust server certificate", variable=self.trust_var,
                       bootstyle="round-toggle").pack(side="left", padx=14)
        r += 1

        box.rowconfigure(r, weight=1)
        r += 1
        bf = tb.Frame(box)
        bf.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        bf.columnconfigure((0, 1, 2), weight=1)
        self.test_btn = tb.Button(bf, text="Test", bootstyle="secondary-outline", command=self.test)
        self.save_btn = tb.Button(bf, text="Save", bootstyle="secondary-outline", command=self.save)
        self.connect_btn = tb.Button(bf, text="Connect  ▶", bootstyle="primary", command=self.connect)
        self.test_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.save_btn.grid(row=0, column=1, sticky="ew", padx=4)
        self.connect_btn.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        self.app.register_busy(self.load_btn, self.test_btn, self.save_btn, self.connect_btn)

        for w in (self.server_entry, self.user_entry, self.pwd_entry, self.db_combo):
            w.bind("<Return>", lambda e: self.connect())

    def _auth_changed(self):
        state = "disabled" if self.auth_var.get() == "windows" else "normal"
        for w in (self.user_entry, self.pwd_entry, self.show_btn):
            w.configure(state=state)

    def new_connection(self):
        self.tree.selection_remove(*self.tree.selection())
        for k, var in self.v.items():
            var.set(AUTO_DRIVER if k == "driver" else "")
        self.auth_var.set("sql")
        self.encrypt_var.set(False)
        self.trust_var.set(True)
        self.db_combo.configure(values=[])
        self._auth_changed()
        self.server_entry.focus_set()

    def fill_form(self, info):
        self.v["alias"].set(info.alias)
        self.v["server"].set(info.server)
        self.v["database"].set(info.database)
        self.v["user"].set(info.username)
        self.v["pwd"].set(get_password(info))
        self.v["driver"].set(info.driver or AUTO_DRIVER)
        self.auth_var.set(info.auth)
        self.encrypt_var.set(info.encrypt)
        self.trust_var.set(info.trust_cert)
        self._auth_changed()

    def form_info(self, require_db=True):
        """Build ConnInfo from the form. Note: the password is NOT stripped."""
        server = self.v["server"].get().strip()
        database = self.v["database"].get().strip()
        user = self.v["user"].get().strip()
        auth = self.auth_var.get()
        missing = [n for n, val in [("Server", server), ("Database", database if require_db else "x"),
                                    ("Username", user if auth == "sql" else "x")] if not val]
        if missing:
            self.app.toast(f"Required: {', '.join(missing)}", "warning")
            return None, None
        driver = self.v["driver"].get()
        info = ConnInfo(server=server, database=database or "master", auth=auth,
                        username=user if auth == "sql" else "",
                        driver="" if driver == AUTO_DRIVER else driver,
                        encrypt=self.encrypt_var.get(), trust_cert=self.trust_var.get(),
                        alias=self.v["alias"].get().strip())
        return info, self.v["pwd"].get()

    # ── actions ───────────────────────────────────────────────────
    def load_databases(self):
        info, pwd = self.form_info(require_db=False)
        if not info:
            return

        def work(job):
            db = Database(info, pwd, "master").connect()
            try:
                return db.list_databases()
            finally:
                db.close()

        def ok(dbs):
            self.db_combo.configure(values=dbs)

            self.app.log(f"Found {len(dbs)} databases on {info.server}", "ok")
            self.app.status(f"Found {len(dbs)} databases on {info.server}")

        self.app.run(work, ok, label=f"Loading databases from {info.server}…")

    def test(self):
        info, pwd = self.form_info()
        if not info:
            return

        def work(job):
            db = Database(info, pwd).connect()
            try:
                return db.scalar("SELECT @@VERSION")
            finally:
                db.close()

        def ok(version):
            first = (version or "").splitlines()[0]
            self.app.log(f"Test OK: {info.server} / {info.database} — {first}", "ok")
            self.app.status("Connection test succeeded")
            self.app.toast("Connection test succeeded")

        self.app.run(work, ok, label=f"Testing {info.server}…")

    def save(self, info=None, pwd=None, quiet=False):
        if info is None:
            info, pwd = self.form_info()
            if not info:
                return
        existing = self.app.store.find(info.key)
        if existing:
            info.last_used = existing.last_used
        try:
            self.app.store.upsert(info, pwd)
        except Exception as e:
            self.app.log(f"Could not save connection: {e}", "err")
            return
        if not quiet:
            self.app.log(f"Saved {info.label}", "ok")
            self.app.toast("Connection saved")
        self.reload()

    def connect(self):
        info, pwd = self.form_info()
        if not info:
            return

        def work(job):
            return Database(info, pwd).connect()

        def ok(db):
            info.last_used = time.time()
            self.save(info, pwd, quiet=True)
            self.app.on_connected(db, info, pwd)

        self.app.run(work, ok, label=f"Connecting to {info.server} / {info.database}…")

    def on_show(self):
        self.reload()
        if not self.v["server"].get():
            items = self.app.store.sorted()
            if items:
                self.fill_form(items[0])
        self.server_entry.focus_set()

