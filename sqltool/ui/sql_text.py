"""Text editor widget with line numbers and lightweight T-SQL highlighting."""
import re
import tkinter as tk

import ttkbootstrap as tb

KEYWORDS = r"""ADD ALL ALTER AND ANY AS ASC BEGIN BETWEEN BY CASCADE CASE CAST CHECK CLUSTERED
COLUMN COMMIT CONSTRAINT CONVERT CREATE CROSS CURSOR DECLARE DEFAULT DELETE DESC DISTINCT DROP
ELSE END EXEC EXECUTE EXISTS FETCH FOREIGN FROM FULL FUNCTION GO GRANT GROUP HAVING IDENTITY IF
IN INCLUDE INDEX INNER INSERT INTO IS JOIN KEY LEFT LIKE MERGE NOCHECK NONCLUSTERED NOT NULL OF
OFF ON OR ORDER OUTER OUTPUT OVER PARTITION PERSISTED PRIMARY PROC PROCEDURE REFERENCES RETURN
RETURNS RIGHT ROLLBACK SCHEMABINDING SELECT SET TABLE THEN TO TOP TRAN TRANSACTION TRIGGER
TRUNCATE UNION UNIQUE UPDATE USE VALUES VIEW WHEN WHERE WHILE WITH""".split()

TYPES = r"""BIGINT BINARY BIT CHAR DATE DATETIME DATETIME2 DATETIMEOFFSET DECIMAL FLOAT INT MONEY
NCHAR NUMERIC NVARCHAR REAL SMALLDATETIME SMALLINT SMALLMONEY SYSNAME TIME TINYINT
UNIQUEIDENTIFIER VARBINARY VARCHAR XML MAX""".split()

TOKEN_RE = re.compile(
    r"(?P<comment>--[^\n]*|/\*.*?\*/)"
    r"|(?P<string>N?'(?:[^']|'')*')"
    r"|(?P<ident>\[(?:[^\]]|\]\])*\])"
    r"|(?P<number>\b\d+(?:\.\d+)?\b)"
    r"|(?P<word>@{0,2}[A-Za-z_][A-Za-z0-9_]*)",
    re.DOTALL)
_KW = set(KEYWORDS)
_TY = set(TYPES)

PALETTES = {
    "dark":  dict(bg="#1b1f24", fg="#d6deeb", gutter_bg="#171a1e", gutter_fg="#5c6773",
                  keyword="#82aaff", type="#c792ea", string="#ecc48d", comment="#637777",
                  number="#f78c6c", ident="#addb67", variable="#7fdbca", cursor="#82aaff",
                  select="#2b3f5c"),
    "light": dict(bg="#ffffff", fg="#24292e", gutter_bg="#f6f8fa", gutter_fg="#959da5",
                  keyword="#0b56c5", type="#6f42c1", string="#a5480f", comment="#6a737d",
                  number="#005cc5", ident="#22863a", variable="#e36209", cursor="#0b56c5",
                  select="#c8e1ff"),
}


class SqlText(tb.Frame):
    def __init__(self, master, font=("Consolas", 10), **kw):
        super().__init__(master, **kw)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.gutter = tk.Canvas(self, width=44, highlightthickness=0, bd=0)
        self.gutter.grid(row=0, column=0, sticky="ns")
        self.text = tk.Text(self, wrap="none", undo=True, maxundo=-1, font=font,
                            relief="flat", bd=0, padx=8, pady=6, highlightthickness=0,
                            tabs=("4c",))
        self.text.grid(row=0, column=1, sticky="nsew")
        vs = tb.Scrollbar(self, orient="vertical", command=self._yview)
        hs = tb.Scrollbar(self, orient="horizontal", command=self.text.xview)
        vs.grid(row=0, column=2, sticky="ns")
        hs.grid(row=1, column=1, sticky="ew")
        self.text.configure(yscrollcommand=lambda *a: (vs.set(*a), self._draw_gutter()),
                            xscrollcommand=hs.set)

        self._after = None
        self.text.bind("<<Modified>>", self._on_modified)
        self.text.bind("<Configure>", lambda e: self._draw_gutter())
        self.set_palette("dark")

    # ── public API ────────────────────────────────────────────────
    def get(self):
        return self.text.get("1.0", "end-1c")

    def set(self, content):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.edit_reset()
        self.text.mark_set("insert", "1.0")
        self.text.see("1.0")
        self._highlight()

    def append(self, content):
        if self.get().strip():
            content = "\n" + content
        self.text.insert("end", content)
        self.text.see("end")
        self._highlight()

    def clear(self):
        self.set("")

    def set_palette(self, mode):
        p = PALETTES[mode]
        self.text.configure(bg=p["bg"], fg=p["fg"], insertbackground=p["cursor"],
                            selectbackground=p["select"], selectforeground=p["fg"],
                            inactiveselectbackground=p["select"])
        self.gutter.configure(bg=p["gutter_bg"])
        self._gutter_fg = p["gutter_fg"]
        for tag in ("keyword", "type", "string", "comment", "number", "ident", "variable"):
            self.text.tag_configure(tag, foreground=p[tag])
        self.text.tag_configure("comment", font=self.text.cget("font"))
        self.text.tag_raise("sel")
        self._draw_gutter()

    # ── internals ─────────────────────────────────────────────────
    def _yview(self, *args):
        self.text.yview(*args)
        self._draw_gutter()

    def _on_modified(self, _=None):
        self.text.edit_modified(False)
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(150, self._highlight)
        self._draw_gutter()

    def _highlight(self):
        self._after = None
        t = self.text
        content = t.get("1.0", "end-1c")
        for tag in ("keyword", "type", "string", "comment", "number", "ident", "variable"):
            t.tag_remove(tag, "1.0", "end")
        if len(content) > 2_000_000:          # don't stall on huge batches
            return
        for m in TOKEN_RE.finditer(content):
            kind = m.lastgroup
            if kind == "word":
                w = m.group().upper()
                if w.startswith("@"):
                    kind = "variable"
                elif w in _KW:
                    kind = "keyword"
                elif w in _TY:
                    kind = "type"
                else:
                    continue
            t.tag_add(kind, f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        self._draw_gutter()

    def _draw_gutter(self):
        g = self.gutter
        g.delete("all")
        idx = self.text.index("@0,0")
        last = int(self.text.index("end-1c").split(".")[0])
        g.configure(width=max(36, 10 + 8 * len(str(last))))
        while True:
            info = self.text.dlineinfo(idx)
            if info is None:
                break
            line = idx.split(".")[0]
            g.create_text(int(g.cget("width")) - 6, info[1], anchor="ne", text=line,
                          fill=self._gutter_fg, font=("Consolas", 9))
            nxt = self.text.index(f"{idx}+1line")
            if nxt == idx:
                break
            idx = nxt
