"""Script table data as INSERT statements from a user-supplied SELECT."""
import datetime as dt
import re
import struct
from dataclasses import dataclass, field

from .scripting import RawLiteral, insert_statement

EDITOR_ROW_LIMIT = 20_000
PROGRESS_EVERY = 500

_NAME = r'(?:\[(?:[^\]]|\]\])+\]|"[^"]+"|[A-Za-z_#@][\w@#$]*)'
_FROM_TARGET = re.compile(rf"\bFROM\s+({_NAME}(?:\s*\.\s*{_NAME}){{0,3}})", re.IGNORECASE)
_TOKENS = re.compile(r"--[^\n]*|/\*.*?\*/|N?'(?:[^']|'')*'|\[(?:[^\]]|\]\])*\]|\"[^\"]*\"", re.DOTALL)
_WRITE_WORDS = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|EXEC|EXECUTE|DROP|ALTER|CREATE|TRUNCATE|"
                          r"GRANT|REVOKE|DENY|BACKUP|RESTORE|DBCC|SHUTDOWN|KILL|INTO|DECLARE|SET)\b",
                          re.IGNORECASE)


# ODBC types read raw so no precision is lost (Python datetimes stop at microseconds,
# and pyodbc can't read DATETIMEOFFSET at all).
SQL_TYPE_TIMESTAMP = 93
SQL_SS_TIMESTAMPOFFSET = -155


def _fraction(ns):
    """Nanoseconds -> '' / '.fff' / up to 7 digits (SQL Server's 100ns resolution)."""
    if not ns:
        return ""
    if ns % 1_000_000 == 0:
        return f".{ns // 1_000_000:03d}"
    return "." + f"{ns:09d}"[:7].rstrip("0")


_EPOCH_1900 = dt.datetime(1900, 1, 1)


def _conv_timestamp(raw):
    """SQL_TYPE_TIMESTAMP arrives as: 16-byte TIMESTAMP_STRUCT (datetime2),
    8-byte native DATETIME (days since 1900, 1/300 s ticks) or 4-byte SMALLDATETIME."""
    if raw is None:
        return None
    if len(raw) >= 16:
        y, mo, d, h, mi, s, ns = struct.unpack("<hHHHHHI", raw[:16])
        return RawLiteral(f"'{y:04d}{mo:02d}{d:02d} {h:02d}:{mi:02d}:{s:02d}{_fraction(ns)}'")
    if len(raw) == 8:
        days, ticks = struct.unpack("<iI", raw)
        ms = round(ticks * 10 / 3)                 # 1/300 s -> ms, as SQL Server displays it
        v = _EPOCH_1900 + dt.timedelta(days=days, milliseconds=ms)
        frac = f".{v.microsecond // 1000:03d}" if v.microsecond else ""
    elif len(raw) == 4:
        days, minutes = struct.unpack("<HH", raw)
        v = _EPOCH_1900 + dt.timedelta(days=days, minutes=minutes)
        frac = ""
    else:
        raise ValueError(f"Unexpected datetime value ({len(raw)} bytes)")
    return RawLiteral(f"'{v:%Y%m%d %H:%M:%S}{frac}'")


def _conv_offset(raw):
    if raw is None:
        return None
    y, mo, d, h, mi, s, ns, th, tm = struct.unpack("<hHHHHHIhh", raw[:20])
    sign = "-" if th < 0 or tm < 0 else "+"
    return RawLiteral(f"'{y:04d}{mo:02d}{d:02d} {h:02d}:{mi:02d}:{s:02d}{_fraction(ns)} "
                      f"{sign}{abs(th):02d}:{abs(tm):02d}'")


CONVERTERS = {SQL_TYPE_TIMESTAMP: _conv_timestamp, SQL_SS_TIMESTAMPOFFSET: _conv_offset}


class TooManyRows(Exception):
    def __init__(self, limit):
        super().__init__(f"More than {limit:,} rows — too many for the editor. Use 'Output: File' instead.")
        self.limit = limit


def _mask(sql, keep_brackets=False):
    """Blank out comments and string literals (and bracketed names unless keep_brackets)."""
    def repl(m):
        tok = m.group()
        if keep_brackets and tok[0] in '["':
            return tok
        if tok.startswith(("--", "/*")):
            return " "
        return "''" if "'" in tok[:2] else "[x]"
    return _TOKENS.sub(repl, sql)


def validate_select(sql):
    """Allow a single read-only SELECT (or WITH … SELECT). Raises ValueError otherwise."""
    masked = _mask(sql).strip()
    if not masked:
        raise ValueError("Enter a SELECT statement.")
    parts = [p for p in masked.split(";") if p.strip()]
    if len(parts) > 1:
        raise ValueError("Only one statement is allowed.")
    first = re.match(r"\s*(\w+)", parts[0])
    if not first or first.group(1).upper() not in ("SELECT", "WITH"):
        raise ValueError("Only SELECT statements are allowed (the query must start with SELECT or WITH).")
    bad = _WRITE_WORDS.search(parts[0])
    if bad:
        raise ValueError(f"'{bad.group(1).upper()}' is not allowed — this feature only reads data.")


def guess_target(sql):
    """(table text as written, needs_check). needs_check is True for joins, CTEs or subqueries."""
    masked = _mask(sql, keep_brackets=True)
    m = _FROM_TARGET.search(masked)
    target = re.sub(r"\s*\.\s*", ".", m.group(1)) if m else None
    needs_check = bool(re.search(r"\bJOIN\b|\bAPPLY\b|^\s*WITH\b", masked, re.IGNORECASE)) or \
        bool(re.search(r"\bFROM\s*\(", masked, re.IGNORECASE)) or \
        bool(m and re.match(r"\s*,", masked[m.end():]))
    return target, needs_check


def table_text(schema, name):
    """Table reference in the user's INSERT style: bare name for dbo, brackets only when needed."""
    from .scripting import ident
    return ident(name) if schema.lower() == "dbo" else f"{ident(schema)}.{ident(name)}"


def select_all_sql(schema, name):
    return f"SELECT * FROM {table_text(schema, name)}"


@dataclass
class ColumnPlan:
    keep: list = field(default_factory=list)        # indexes into the result row
    names: list = field(default_factory=list)
    skipped: list = field(default_factory=list)     # computed / rowversion
    identity: bool = False
    unknown: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)


def plan_columns(result_cols, table_meta=None):
    plan = ColumnPlan()
    seen = set()
    for c in result_cols:
        if c.lower() in seen:
            plan.duplicates.append(c)
        seen.add(c.lower())
    meta = {c.name.lower(): c for c in table_meta.columns} if table_meta else None
    for i, c in enumerate(result_cols):
        if meta is not None:
            col = meta.get(c.lower())
            if col is None:
                plan.unknown.append(c)
                continue
            if col.computed or col.type_name.lower() in ("timestamp", "rowversion"):
                plan.skipped.append(c)
                continue
            if col.is_identity:
                plan.identity = True
            c = col.name
        plan.keep.append(i)
        plan.names.append(c)
    return plan


@dataclass
class ScriptResult:
    rows: int = 0
    text: str = None
    skipped: list = field(default_factory=list)
    identity: bool = False
    warnings: list = field(default_factory=list)


def script_rows(db, sql, target, write, job=None, wrap_identity=True, limit=None):
    """Run the SELECT and call write(text) for each INSERT. Runs on a worker thread."""
    from . import metadata as md

    validate_select(sql)
    if not target:
        raise ValueError("Enter the target table for the INSERT statements.")
    result = ScriptResult()
    table_meta = None
    found = [o for o in md.resolve_object(db, target) if o.type == "U"]
    if found:
        table_meta = md.get_table_meta(db, found[0])
    else:
        result.warnings.append(f"Table {target} not found in {db.database}; "
                               "all returned columns are used as-is.")

    plan = None
    for item in db.stream(sql, converters=CONVERTERS):
        if plan is None:                       # first item is cursor.description
            names = [d[0] for d in item]
            if any(not n for n in names):
                raise ValueError("Every column needs a name (add an alias to expressions).")
            plan = plan_columns(names, table_meta)
            if plan.duplicates:
                raise ValueError("Duplicate column names: " + ", ".join(plan.duplicates))
            if plan.unknown:
                raise ValueError(f"Not columns of {target}: " + ", ".join(plan.unknown))
            if not plan.names:
                raise ValueError("No insertable columns.")
            result.skipped, result.identity = plan.skipped, plan.identity and wrap_identity
            if result.identity:
                write(f"SET IDENTITY_INSERT {target} ON")
            continue
        for row in item:
            if limit and result.rows >= limit:
                raise TooManyRows(limit)
            write(insert_statement(target, plan.names, [row[i] for i in plan.keep]))
            result.rows += 1
        if job:
            job.check()
            job.progress(result.rows)
    if result.identity:
        write(f"SET IDENTITY_INSERT {target} OFF")
    return result
