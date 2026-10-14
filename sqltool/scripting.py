"""Pure script builders: metadata in, T-SQL text out. No DB or UI access here."""
import datetime as dt
import heapq
import re
import uuid
from decimal import Decimal
from dataclasses import dataclass, field

from .metadata import FUNCTION_TYPES

SEPARATOR = "-- " + "─" * 77
INDENT = "    "


@dataclass
class ScriptOptions:
    header_mode: str = "drop_create"       # drop_create | create_or_alter | definition
    include_grants: bool = True
    grant_roles: list = field(default_factory=lambda: ["SDA_ROLE", "HR_ROLE"])
    include_separator: bool = True
    table_if_not_exists: bool = True
    varchar_to_nvarchar: bool = True
    table_indexes: bool = False
    table_foreign_keys: bool = False
    table_check_constraints: bool = False

    @classmethod
    def from_settings(cls, s):
        return cls(**{k: getattr(s, k) for k in cls.__dataclass_fields__})


# ─────────────────────────────────────────────────────────────────
#  QUOTING
# ─────────────────────────────────────────────────────────────────

def q(name):
    """[bracket] an identifier."""
    return "[" + str(name).replace("]", "]]") + "]"


def qn(schema, name):
    return f"{q(schema)}.{q(name)}"


def lit(text):
    """Escape text for use inside N'...'."""
    return str(text).replace("'", "''")


# ─────────────────────────────────────────────────────────────────
#  MODULES (views, procedures, functions, triggers)
# ─────────────────────────────────────────────────────────────────

def grant_verb(obj_type):
    if obj_type in ("V", "IF", "TF", "FT"):
        return "SELECT"
    if obj_type in ("P", "FN", "FS"):
        return "EXEC"
    return None


_LEADING_CREATE = re.compile(r"^((?:\s+|--[^\n]*\n|/\*.*?\*/)*)CREATE(?!\s+OR\s+ALTER)\b",
                             re.IGNORECASE | re.DOTALL)


def to_create_or_alter(definition):
    return _LEADING_CREATE.sub(r"\1CREATE OR ALTER", definition, count=1)


def drop_header(obj):
    name = qn(obj.schema, obj.name)
    oid = f"OBJECT_ID(N'{lit(name)}')"
    if obj.type == "V":
        return (f"IF EXISTS (SELECT * FROM dbo.sysobjects WHERE id = {oid}"
                f" AND OBJECTPROPERTY(id, N'IsView') = 1)\n    DROP VIEW {name}\nGO")
    if obj.type == "P":
        return (f"IF EXISTS (SELECT * FROM dbo.sysobjects WHERE id = {oid}"
                f" AND OBJECTPROPERTY(id, N'IsProcedure') = 1)\nBEGIN\n"
                f"    DROP PROCEDURE {name}\nEND\nGO")
    if obj.type in FUNCTION_TYPES:
        return (f"IF EXISTS (SELECT * FROM sys.objects WHERE object_id = {oid}\n"
                f"AND type IN (N'FN', N'IF', N'TF', N'FS', N'FT'))\n"
                f"    DROP FUNCTION {name}\nGO")
    if obj.type == "TR":
        return (f"IF EXISTS (SELECT * FROM sys.triggers WHERE object_id = {oid})\n"
                f"    DROP TRIGGER {name}\nGO")
    raise ValueError(f"Unsupported object type: {obj.type}")


def grant_footer(obj, opts):
    lines = ["GO"]
    verb = grant_verb(obj.type)
    if opts.include_grants and verb:
        for role in opts.grant_roles:
            role = role.strip()
            if role:
                lines += [f"GRANT {verb} ON {qn(obj.schema, obj.name)} TO {q(role) if not role.isidentifier() else role}",
                          "GO"]
    if opts.include_separator:
        lines.append(SEPARATOR)
    return "\n".join(lines)


def build_module_script(obj, definition, opts):
    if definition is None:
        raise ValueError(f"No definition available for {obj.full_name} "
                         "(encrypted, or no VIEW DEFINITION permission).")
    body = definition.strip()
    if opts.header_mode == "create_or_alter":
        return f"{to_create_or_alter(body)}\n{grant_footer(obj, opts)}"
    if opts.header_mode == "definition":
        return f"{body}\nGO" + (f"\n{SEPARATOR}" if opts.include_separator else "")
    return f"{drop_header(obj)}\n{body}\n{grant_footer(obj, opts)}"


# ─────────────────────────────────────────────────────────────────
#  TABLES
# ─────────────────────────────────────────────────────────────────

_LEN_TYPES   = {"char", "varchar", "binary", "varbinary"}
_NLEN_TYPES  = {"nchar", "nvarchar"}
_PREC_TYPES  = {"decimal", "numeric"}
_SCALE_TYPES = {"datetime2", "time", "datetimeoffset"}


def format_type(col, varchar_to_nvarchar=False):
    if col.user_type_schema:
        return qn(col.user_type_schema, col.type_name)
    t = col.type_name.lower()
    if t == "varchar" and varchar_to_nvarchar:
        if col.max_length == -1 or col.max_length > 4000:
            return "NVARCHAR(MAX)"
        return f"NVARCHAR({col.max_length})"
    if t in _LEN_TYPES:
        return f"{t.upper()}({'MAX' if col.max_length == -1 else col.max_length})"
    if t in _NLEN_TYPES:
        return f"{t.upper()}({'MAX' if col.max_length == -1 else col.max_length // 2})"
    if t in _PREC_TYPES:
        return f"{t.upper()}({col.precision},{col.scale})"
    if t in _SCALE_TYPES:
        return f"{t.upper()}({col.scale})"
    if t == "float" and col.precision and col.precision != 53:
        return f"FLOAT({col.precision})"
    return t.upper()


def column_line(col, opts):
    if col.computed:
        return f"{q(col.name)} AS {col.computed}" + (" PERSISTED" if col.persisted else "")
    parts = [q(col.name), format_type(col, opts.varchar_to_nvarchar)]
    if col.is_identity:
        parts.append(f"IDENTITY({col.seed},{col.increment})")
    parts.append("NULL" if col.nullable else "NOT NULL")
    if col.default_def:
        parts.append(f"CONSTRAINT {q(col.default_name)} DEFAULT {col.default_def}"
                     if col.default_name else f"DEFAULT {col.default_def}")
    return " ".join(parts)


def _key_list(keys):
    return ", ".join(f"{q(c)} {'DESC' if d else 'ASC'}" for c, d in keys)


_INDEX_WITH = ("WITH (PAD_INDEX=OFF,STATISTICS_NORECOMPUTE=OFF,IGNORE_DUP_KEY=OFF,"
               "ALLOW_ROW_LOCKS=ON,ALLOW_PAGE_LOCKS=ON)")


def constraint_line(idx):
    kind = "PRIMARY KEY" if idx.is_pk else "UNIQUE"
    clustered = "CLUSTERED" if idx.type_desc == "CLUSTERED" else "NONCLUSTERED"
    on = f" ON {q(idx.data_space)}" if idx.data_space else ""
    return f"CONSTRAINT {q(idx.name)} {kind} {clustered} ({_key_list(idx.keys)}) {_INDEX_WITH}{on}"


def index_statement(table, idx):
    if idx.type_desc not in ("CLUSTERED", "NONCLUSTERED"):
        return f"-- Skipped {idx.type_desc.lower()} index {q(idx.name)} (not supported by this tool)"
    tname = qn(table.schema, table.name)
    sql = (f"CREATE {'UNIQUE ' if idx.is_unique else ''}{idx.type_desc} INDEX {q(idx.name)}"
           f" ON {tname} ({_key_list(idx.keys)})")
    if idx.includes:
        sql += f" INCLUDE ({', '.join(q(c) for c in idx.includes)})"
    if idx.filter:
        sql += f" WHERE {idx.filter}"
    if idx.data_space:
        sql += f" ON {q(idx.data_space)}"
    return (f"IF NOT EXISTS (SELECT * FROM sys.indexes WHERE object_id = OBJECT_ID(N'{lit(tname)}')"
            f" AND name = N'{lit(idx.name)}')\n{INDENT}{sql}\nGO")


def fk_statement(table, fk):
    tname = qn(table.schema, table.name)
    cols = ", ".join(q(c) for c in fk.columns)
    refs = ", ".join(q(c) for c in fk.ref_columns)
    sql = (f"ALTER TABLE {tname} WITH CHECK ADD CONSTRAINT {q(fk.name)} FOREIGN KEY ({cols})"
           f" REFERENCES {qn(fk.ref_schema, fk.ref_table)} ({refs})")
    if fk.on_delete and fk.on_delete != "NO_ACTION":
        sql += f" ON DELETE {fk.on_delete.replace('_', ' ')}"
    if fk.on_update and fk.on_update != "NO_ACTION":
        sql += f" ON UPDATE {fk.on_update.replace('_', ' ')}"
    out = (f"IF NOT EXISTS (SELECT * FROM sys.foreign_keys WHERE object_id = OBJECT_ID(N'{lit(qn(table.schema, fk.name))}'))\n"
           f"{INDENT}{sql}\nGO")
    if fk.disabled:
        out += f"\nALTER TABLE {tname} NOCHECK CONSTRAINT {q(fk.name)}\nGO"
    return out


def build_table_script(table, opts, separate_fks=False):
    """Returns the CREATE TABLE script. With separate_fks=True returns (script, fk_script)
    so a batch can emit all foreign keys after every table exists."""
    if not table.columns:
        raise ValueError(f"Table {table.schema}.{table.name} has no columns.")
    tname = qn(table.schema, table.name)
    pad = INDENT          # the IF NOT EXISTS wrapper adds one more level below

    items = [column_line(c, opts) for c in table.columns]
    items += [constraint_line(i) for i in table.indexes if i.is_pk]
    items += [constraint_line(i) for i in table.indexes if i.is_unique_constraint]
    if opts.table_check_constraints:
        items += [f"CONSTRAINT {q(c.name)} CHECK {c.definition}" for c in table.checks]

    create = [f"CREATE TABLE {tname} ("]
    create += [f"{pad}{line}," for line in items]
    create[-1] = create[-1].rstrip(",")
    create.append(f"){' ON ' + q(table.data_space) if table.data_space else ''}")

    if opts.table_if_not_exists:
        lines = [f"IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'{lit(tname)}') AND type = N'U')",
                 "BEGIN"]
        lines += [INDENT + l for l in create]
        lines += ["END", "GO"]
    else:
        lines = create + ["GO"]

    if opts.table_check_constraints:
        lines += [f"ALTER TABLE {tname} NOCHECK CONSTRAINT {q(c.name)}\nGO"
                  for c in table.checks if c.disabled]
    if opts.table_indexes:
        lines += [index_statement(table, i) for i in table.indexes
                  if not i.is_pk and not i.is_unique_constraint]

    fk_text = ""
    if opts.table_foreign_keys and table.foreign_keys:
        fk_text = "\n".join(fk_statement(table, fk) for fk in table.foreign_keys)
        if not separate_fks:
            lines.append(fk_text)

    if opts.include_separator:
        lines.append(SEPARATOR)
    script = "\n".join(lines)
    return (script, fk_text) if separate_fks else script


# ─────────────────────────────────────────────────────────────────
#  BATCH ORDERING
# ─────────────────────────────────────────────────────────────────

TYPE_RANK = {"U": 0, "FN": 1, "FS": 1, "IF": 2, "TF": 2, "FT": 2, "V": 3, "P": 4, "TR": 5}


def order_objects(objects, edges=()):
    """Topological order (dependencies first), ties broken by type rank then name.
    edges: (referencing_id, referenced_id). Cycles fall back to rank order."""
    by_id = {o.object_id: o for o in objects}
    deps = {oid: set() for oid in by_id}
    users = {oid: set() for oid in by_id}
    for a, b in edges:
        if a in by_id and b in by_id and a != b:
            deps[a].add(b)
            users[b].add(a)

    def key(o):
        return (TYPE_RANK.get(o.type, 9), o.schema.lower(), o.name.lower(), o.object_id)

    heap = [key(by_id[i]) for i, d in deps.items() if not d]
    heapq.heapify(heap)
    out, done = [], set()
    while heap:
        oid = heapq.heappop(heap)[-1]
        if oid in done:
            continue
        done.add(oid)
        out.append(by_id[oid])
        for u in users[oid]:
            deps[u].discard(oid)
            if not deps[u] and u not in done:
                heapq.heappush(heap, key(by_id[u]))
    out += sorted((o for o in objects if o.object_id not in done), key=key)
    return out


# ─────────────────────────────────────────────────────────────────
#  DATA (INSERT statements)
# ─────────────────────────────────────────────────────────────────

RESERVED = set("""ADD ALL ALTER AND ANY AS ASC AUTHORIZATION BACKUP BEGIN BETWEEN BREAK BROWSE BULK BY
CASCADE CASE CHECK CHECKPOINT CLOSE CLUSTERED COALESCE COLLATE COLUMN COMMIT COMPUTE CONSTRAINT
CONTAINS CONTAINSTABLE CONTINUE CONVERT CREATE CROSS CURRENT CURRENT_DATE CURRENT_TIME
CURRENT_TIMESTAMP CURRENT_USER CURSOR DATABASE DBCC DEALLOCATE DECLARE DEFAULT DELETE DENY DESC
DISK DISTINCT DISTRIBUTED DOUBLE DROP DUMP ELSE END ERRLVL ESCAPE EXCEPT EXEC EXECUTE EXISTS EXIT
EXTERNAL FETCH FILE FILLFACTOR FOR FOREIGN FREETEXT FREETEXTTABLE FROM FULL FUNCTION GOTO GRANT
GROUP HAVING HOLDLOCK IDENTITY IDENTITY_INSERT IDENTITYCOL IF IN INDEX INNER INSERT INTERSECT INTO
IS JOIN KEY KILL LEFT LIKE LINENO LOAD MERGE NATIONAL NOCHECK NONCLUSTERED NOT NULL NULLIF OF OFF
OFFSETS ON OPEN OPENDATASOURCE OPENQUERY OPENROWSET OPENXML OPTION OR ORDER OUTER OVER PERCENT PIVOT
PLAN PRECISION PRIMARY PRINT PROC PROCEDURE PUBLIC RAISERROR READ READTEXT RECONFIGURE REFERENCES
REPLICATION RESTORE RESTRICT RETURN REVERT REVOKE RIGHT ROLLBACK ROWCOUNT ROWGUIDCOL RULE SAVE SCHEMA
SECURITYAUDIT SELECT SEMANTICKEYPHRASETABLE SEMANTICSIMILARITYDETAILSTABLE SEMANTICSIMILARITYTABLE
SESSION_USER SET SETUSER SHUTDOWN SOME STATISTICS SYSTEM_USER TABLE TABLESAMPLE TEXTSIZE THEN TO TOP
TRAN TRANSACTION TRIGGER TRUNCATE TRY_CONVERT TSEQUAL UNION UNIQUE UNPIVOT UPDATE UPDATETEXT USE USER
VALUES VARYING VIEW WAITFOR WHEN WHERE WHILE WITH WITHIN WRITETEXT""".split())

_PLAIN_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_@#$]*$")


def ident(name):
    """Bare identifier when safe (matches the user's INSERT style), otherwise [bracketed]."""
    name = str(name)
    if _PLAIN_IDENT.match(name) and name.upper() not in RESERVED:
        return name
    return q(name)


def _frac(micro):
    if not micro:
        return ""
    return f".{micro // 1000:03d}" if micro % 1000 == 0 else f".{micro:06d}"


class RawLiteral(str):
    """Already-formatted T-SQL literal (e.g. full-precision DATETIME2 from an ODBC converter)."""


def sql_literal(v):
    """Python value (as returned by pyodbc) -> T-SQL literal."""
    if v is None:
        return "NULL"
    if isinstance(v, RawLiteral):
        return str(v)
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, dt.datetime):
        s = v.strftime("%Y%m%d %H:%M:%S") + _frac(v.microsecond)
        if v.utcoffset() is not None:
            off = int(v.utcoffset().total_seconds() // 60)
            s += f" {'+' if off >= 0 else '-'}{abs(off) // 60:02d}:{abs(off) % 60:02d}"
        return f"'{s}'"
    if isinstance(v, dt.date):
        return f"'{v.strftime('%Y%m%d')}'"
    if isinstance(v, dt.time):
        return f"'{v.strftime('%H:%M:%S')}{_frac(v.microsecond)}'"
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "0x" + bytes(v).hex().upper()
    if isinstance(v, uuid.UUID):
        return f"N'{v}'"
    return f"N'{lit(v)}'"


def insert_statement(table_text, columns, row):
    cols = ",".join(ident(c) for c in columns)
    vals = ",".join(sql_literal(v) for v in row)
    return f"INSERT INTO {table_text} ({cols})\nVALUES ({vals})"


# ─────────────────────────────────────────────────────────────────
#  CLIPBOARD
# ─────────────────────────────────────────────────────────────────

def compact(script):
    """v3 copy behaviour: strip every line and drop blank lines."""
    return "\n".join(line.strip() for line in script.splitlines() if line.strip())


def safe_filename(text):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip(". ") or "script"
