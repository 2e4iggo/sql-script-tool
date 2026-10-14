"""Import Excel / CSV files into SQL Server tables."""
import os
from dataclasses import dataclass, field

from .scripting import q, qn

IMPORT_EXTS = (".xlsx", ".xlsm", ".xls", ".csv")
CHUNK = 1000

MODES = {
    "create_append": "Create if missing + append",
    "replace":       "Replace (drop + recreate)",
    "truncate":      "Truncate + insert",
    "append":        "Append only (table must exist)",
}


@dataclass
class ImportItem:
    path: str
    sheet: str = None
    schema: str = "dbo"
    table: str = ""
    mode: str = "create_append"
    rows: int = None
    columns: list = field(default_factory=list)
    status: str = ""
    error: str = ""
    frame: object = None                  # cached DataFrame (cleaned)

    @property
    def file(self):
        return os.path.basename(self.path)

    @property
    def target(self):
        return f"{self.schema}.{self.table}"


# ─────────────────────────────────────────────────────────────────
#  FILES
# ─────────────────────────────────────────────────────────────────

def discover(folder):
    return sorted(os.path.join(folder, f) for f in os.listdir(folder)
                  if f.lower().endswith(IMPORT_EXTS)
                  and not f.startswith("~$")                    # Excel lock files
                  and os.path.isfile(os.path.join(folder, f)))


def list_sheets(path):
    if path.lower().endswith(".csv"):
        return [None]
    import pandas as pd
    with pd.ExcelFile(path) as xl:
        return list(xl.sheet_names)


def read_frame(path, sheet=None, nrows=None):
    import pandas as pd
    opts = dict(dtype=str, keep_default_na=False, na_filter=False, nrows=nrows)
    if path.lower().endswith(".csv"):
        try:
            df = pd.read_csv(path, encoding="utf-8-sig", **opts)
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="cp1252", **opts)
    else:
        df = pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, **opts)
    return clean_frame(df)


def clean_frame(df):
    """Drop blank / 'Unnamed: n' header columns; strip header names (as v3)."""
    keep = [c for c in df.columns
            if str(c).strip() and not str(c).strip().lower().startswith("unnamed")]
    df = df[keep]
    df.columns = [str(c).strip() for c in keep]
    return df


def frame_rows(df):
    """Rows as lists: empty cells and the text NULL become None; all-empty rows skipped."""
    out = []
    for tup in df.itertuples(index=False, name=None):
        vals = []
        for v in tup:
            s = "" if v is None else str(v).strip()
            vals.append(None if not s or s.upper() == "NULL" else s)
        if any(v is not None for v in vals):
            out.append(vals)
    return out


def build_plan(paths, schema="dbo", mode="create_append", on_item=None, job=None):
    """Expand files into one ImportItem per file/sheet, reading each to count rows."""
    items = []
    for path in paths:
        if job:
            job.check()
        base = os.path.splitext(os.path.basename(path))[0].strip()
        try:
            sheets = list_sheets(path)
        except Exception as e:
            item = ImportItem(path=path, schema=schema, table=base, mode=mode,
                              status="error", error=str(e))
            items.append(item)
            if on_item:
                on_item(item)
            continue
        for sheet in sheets:
            table = base if len(sheets) == 1 else f"{base}_{str(sheet).strip()}"
            item = ImportItem(path=path, sheet=sheet, schema=schema, table=table, mode=mode)
            try:
                df = read_frame(path, sheet)
                item.frame, item.columns = df, list(df.columns)
                item.rows = len(frame_rows(df)) if len(df.columns) else 0
                item.status = "ready" if item.columns else "error"
                if not item.columns:
                    item.error = "No valid columns found."
            except Exception as e:
                item.status, item.error = "error", str(e)
            items.append(item)
            if on_item:
                on_item(item)
    return items


def column_check(table_cols, file_cols):
    """Returns (file columns missing from the table, table columns missing from the file)."""
    t = {c.lower() for c in table_cols}
    f = {c.lower() for c in file_cols}
    return ([c for c in file_cols if c.lower() not in t],
            [c for c in table_cols if c.lower() not in f])


# ─────────────────────────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────────────────────────

def run_item(db, item, job=None, on_progress=None):
    """Import one item in its own transaction. Returns rows inserted. Rolls back on error."""
    import pyodbc
    from .metadata import get_table_columns

    df = item.frame if item.frame is not None else read_frame(item.path, item.sheet)
    file_cols = list(df.columns)
    if not file_cols:
        raise ValueError("No valid columns found.")
    rows = frame_rows(df)
    tname = qn(item.schema, item.table)

    with db.lock:
        existing = get_table_columns(db, item.schema, item.table)
        conn = db.conn
        cur = conn.cursor()
        try:
            if item.mode == "replace" and existing is not None:
                cur.execute(f"DROP TABLE {tname}")
                existing = None
            if existing is None:
                if item.mode in ("append", "truncate"):
                    raise ValueError(f"Table {tname} does not exist.")
                cur.execute(f"CREATE TABLE {tname} ("
                            + ", ".join(f"{q(c)} NVARCHAR(MAX)" for c in file_cols) + ")")
                target_cols = file_cols
            else:
                missing, _ = column_check(existing, file_cols)
                if missing:
                    raise ValueError("Columns not in table: " + ", ".join(missing))
                lookup = {c.lower(): c for c in existing}
                target_cols = [lookup[c.lower()] for c in file_cols]
                if item.mode == "truncate":
                    try:
                        cur.execute(f"TRUNCATE TABLE {tname}")
                    except pyodbc.Error:          # e.g. referenced by a foreign key
                        cur.execute(f"DELETE FROM {tname}")

            if rows:
                cur.fast_executemany = True
                cur.setinputsizes([(pyodbc.SQL_WVARCHAR, 0, 0)] * len(target_cols))
                sql = (f"INSERT INTO {tname} ({', '.join(q(c) for c in target_cols)})"
                       f" VALUES ({', '.join('?' * len(target_cols))})")
                for start in range(0, len(rows), CHUNK):
                    if job:
                        job.check()
                    cur.executemany(sql, rows[start:start + CHUNK])
                    if on_progress:
                        on_progress(min(start + CHUNK, len(rows)), len(rows))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            item.frame = None
    return len(rows)
