# SQL Script Tool v4: specification

This is the behaviour contract. Change it deliberately: the scripts the tool writes go into deployment packages, so output changes reach production.

## 1. Scope

| Feature | In scope |
|---|---|
| Script modules | Views (V), procedures (P), functions (FN, IF, TF, FS, FT), DML triggers (TR) |
| Script tables | User tables (U): columns, PK, unique constraints; optional indexes, FKs, checks |
| Batch | Many objects in one run, in dependency order |
| Import | CSV, XLSX, XLSM, XLS (XLS needs `xlrd`) |
| Out of scope | Synonyms, sequences, types, schemas, users/permissions, partitioning, columnstore / XML / spatial indexes (skipped with a comment), data scripting (INSERTs) |

## 2. Connections

- **Stored fields:** `server, database, auth (sql|windows), username, driver, encrypt, trust_cert, alias, last_used`.
- **Identity:** a connection is identified by `(server, database, auth, username)`, compared case-insensitively. Saving with the same identity **replaces** the old entry, which is how passwords get updated.
- **Passwords:**
  - Stored with `keyring` under service `SQLScriptTool`, key `"{server}|{username}"`.
  - One secret is shared by all databases on the same server and login.
  - Deleting the last connection that uses a secret also deletes the secret.
  - Passwords are **never stripped**: leading and trailing spaces are kept.
- **Connection string:**
  - Every value is brace-quoted (`{…}`, with `}` doubled), so `;` `{` `}` in passwords are safe.
  - Windows auth adds `Trusted_Connection=yes`.
  - Always sets `Encrypt=yes|no`. Adds `TrustServerCertificate=yes` when `trust_cert` is set.
- **Driver auto-detect order:** ODBC Driver 18 → 17 → 13 → SQL Server Native Client 11.0 → `SQL Server`.
- **One connection per session:**
  - `Database` holds one `pyodbc` connection behind an `RLock`.
  - Read queries roll back afterwards so they release locks.
  - On a link failure (SQLSTATE `08xxx` or `OperationalError`) it reconnects once.
- **v3 migration:**
  - If `~/conn_details.pkl` exists at startup, each `{server, database, uid, pwd}` entry is imported and its password moved to keyring.
  - The file is then renamed to `conn_details.pkl.bak`.
  - Entries already present are skipped.

## 3. Object browser

- **Source query:** `sys.objects` joined with `sys.schemas`, where `type IN (U,V,P,FN,IF,TF,FS,FT,TR)` and `is_ms_shipped = 0`.
- **Grouping:** by category (Tables / Views / Procedures / Functions / Triggers). Groups with ≤200 items, or any group while a filter is active, start expanded.
- **Filter:** whitespace-separated terms, all of which must appear (case-insensitive) in `schema.name`.
- **Enter in the filter:**
  - If exactly one object's `name` or `schema.name` equals the text (brackets ignored), generate it.
  - Otherwise move focus to the first result.
- **Generate with nothing selected but filter text present:**
  - Resolve the text on the server with `PARSENAME`.
  - Prefer the `dbo` schema when the name exists in several schemas, and log a warning.
- **Selecting a group header** selects all of its children.

## 4. Module scripts

Inputs: `ObjectInfo(schema, name, type)` and `OBJECT_DEFINITION(object_id)`. A `NULL` definition raises *"No definition available …"*.

### Header modes

**`drop_create`** (default, v3 layout):

```
<drop header>
<definition, stripped>
GO
GRANT <verb> ON [schema].[name] TO <role>     -- per role, each followed by GO
GO
-- ─────…                                       -- if separator on
```

The drop header depends on the object type:

| Type | Drop header |
|---|---|
| V | `IF EXISTS (SELECT * FROM dbo.sysobjects WHERE id = OBJECT_ID(N'[s].[n]') AND OBJECTPROPERTY(id, N'IsView') = 1)` → `DROP VIEW` → `GO` |
| P | same check with `IsProcedure`, then `BEGIN DROP PROCEDURE … END` → `GO` |
| FN/IF/TF/FS/FT | `IF EXISTS (SELECT * FROM sys.objects WHERE object_id = … AND type IN (N'FN', N'IF', N'TF', N'FS', N'FT'))` → `DROP FUNCTION` → `GO` |
| TR | `IF EXISTS (SELECT * FROM sys.triggers WHERE object_id = …)` → `DROP TRIGGER` → `GO` |

**`create_or_alter`:**
- No drop header.
- The first `CREATE` keyword (after any leading whitespace or comments) becomes `CREATE OR ALTER`. It is left alone if it already says that.
- Grants and separator as above.

**`definition`:** the definition, then `GO`, then the optional separator. No grants.

### Grant verbs

| Types | Verb |
|---|---|
| V, IF, TF, FT | `SELECT` |
| P, FN, FS | `EXEC` |
| TR | none |

- Roles come from `settings.grant_roles`.
- A role that isn't a plain identifier is bracketed.

## 5. Table scripts

Source: `sys.columns`, `sys.types`, `sys.identity_columns`, `sys.computed_columns`, `sys.default_constraints`, `sys.indexes`, `sys.index_columns`, `sys.data_spaces`, `sys.foreign_keys`, `sys.foreign_key_columns`, `sys.check_constraints`.

### Layout (IF NOT EXISTS on)

```
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[s].[t]') AND type = N'U')
BEGIN
    CREATE TABLE [s].[t] (
        <column>,                     -- in column_id order
        CONSTRAINT [pk] PRIMARY KEY CLUSTERED|NONCLUSTERED (<keys>) WITH (...) ON [fg],
        CONSTRAINT [uq] UNIQUE ... ,  -- unique constraints
        CONSTRAINT [ck] CHECK (...)   -- if check constraints on
    ) ON [fg]
END
GO
<CREATE INDEX statements>          -- if indexes on, each wrapped in IF NOT EXISTS + GO
<ALTER TABLE … FOREIGN KEY>        -- if FKs on, each wrapped in IF NOT EXISTS + GO
-- ─────…                           -- if separator on
```

- With IF NOT EXISTS off, it's just `CREATE TABLE … GO` with one level of indent.
- Disabled checks and FKs get a `NOCHECK CONSTRAINT` statement afterwards.
- Key lists keep `key_ordinal` order and print `ASC`/`DESC`.
- The PK/UQ `WITH` clause is fixed: `PAD_INDEX=OFF, STATISTICS_NORECOMPUTE=OFF, IGNORE_DUP_KEY=OFF, ALLOW_ROW_LOCKS=ON, ALLOW_PAGE_LOCKS=ON`.

### Column line

- Regular column: `[name] TYPE [IDENTITY(seed,incr)] NULL|NOT NULL [CONSTRAINT [df] DEFAULT <def>]`
- Computed column: `[name] AS <definition> [PERSISTED]`

### Type formatting (`format_type`)

| sys.types name | Output |
|---|---|
| char, varchar, binary, varbinary | `TYPE(n)`; `-1` → `MAX` |
| nchar, nvarchar | `TYPE(n/2)`; `-1` → `MAX` |
| varchar with VARCHAR→NVARCHAR on | `NVARCHAR(n)`; `n > 4000` or `MAX` → `NVARCHAR(MAX)` |
| decimal, numeric | `TYPE(p,s)` |
| datetime2, time, datetimeoffset | `TYPE(scale)` |
| float | `FLOAT` if precision 53, else `FLOAT(p)` |
| user-defined alias type | `[schema].[type]` |
| anything else | upper-case name (`INT`, `DATETIME`, `BIT`, `SYSNAME`, …) |

### Batch FK handling

In a batch, each table's FKs are taken out of the table script and emitted together at the end under `-- Foreign keys`. In per-object files, each table's FKs stay in its own file.

## 6. Batch ordering

1. Edges come from `sys.sql_expression_dependencies` plus `sys.foreign_keys`, limited to the selected objects.
2. A topological sort puts dependencies first.
3. Ties are broken by type rank `U=0, FN/FS=1, IF/TF/FT=2, V=3, P=4, TR=5`, then by schema and name.
4. Objects in a cycle are appended in rank order, never dropped.
5. A failure on one object is logged and the rest continue.

## 7. Copy and save

- **Copy:**
  - With `compact_copy` on (default, v3 behaviour), each line is stripped and blank lines are removed.
  - Off copies the text verbatim.
- **Save:**
  - Files are UTF-8 **with BOM** and CRLF line endings.
  - Per-object files are named `schema.name.sql`, with invalid filename characters replaced by `_`.
  - The per-object option is offered only when the editor still holds exactly the last generated batch.

## 8. Import

### Reading files

- **Discovery:** `*.xlsx|xlsm|xls|csv`, skipping `~$*` lock files. Non-recursive.
- **Read options:** `dtype=str, keep_default_na=False, na_filter=False`.
  - CSV is tried as `utf-8-sig` first, then `cp1252`.
- **Header cleaning:** columns whose header is blank or starts with `unnamed` are dropped. Header names are stripped.
- **Row cleaning:**
  - Each cell is stripped.
  - `""` and `NULL` (any case) become `None`.
  - Rows that are entirely `None` are skipped.
- **Plan:**
  - One item per CSV or per Excel sheet.
  - Default table name: the file's base name, or `base_sheet` for workbooks with several sheets.
  - Schema and mode come from Settings defaults.

### Running an item

Each item runs in its own transaction:

1. Look up the existing table with `OBJECT_ID(QUOTENAME(schema)+'.'+QUOTENAME(table), 'U')`.
2. `replace` + exists → `DROP TABLE`.
3. Missing table:
   - `append` or `truncate` → error.
   - Otherwise `CREATE TABLE` with all columns `NVARCHAR(MAX)`.
4. Existing table:
   - Columns are matched case-insensitively.
   - File columns that aren't in the table → error.
   - Table columns that aren't in the file stay NULL.
   - `truncate` runs `TRUNCATE TABLE`, falling back to `DELETE` (for example when an FK references the table).
5. Insert with `fast_executemany` and `setinputsizes(SQL_WVARCHAR, 0, 0)`, in chunks of 1000. A cancel is checked between chunks.
6. Commit. Any exception or cancel → rollback.

### Preview check

| Situation | Message |
|---|---|
| Table missing, mode creates it | "will be created" |
| Table missing, `append`/`truncate` | error: "does not exist (mode requires it)" |
| `replace` and table exists | warning: will be DROPPED |
| Otherwise | missing columns (error) / table-only columns (OK) / "columns match" |

## 9. UI and threading

- All database and file work runs in `worker.run_bg`. Results come back to the Tk thread through a polled queue.
- `App.run` allows **one job at a time**:
  - It disables the registered busy widgets and shows the progress bar, plus a Cancel button for cancellable jobs.
  - Busy state is cleared **before** the `on_ok` / `on_err` callbacks run, so a callback can start a follow-up job.
- The import dialog's preview check runs with `run_bg` directly. It doesn't take the app's busy slot, and the DB lock serialises it with any running job.
- The window size is clamped to the screen on startup.
- Themes are `bootstrap-dark` (default) and `bootstrap-light`. The editor and log use their own palettes, switched with the theme.

## 10. Security

- All catalog queries take user input only as `?` parameters.
- Identifiers in generated DDL go through `q()` (brackets, `]` → `]]`). String literals go through `lit()` (`'` → `''`).
- `get_dependencies` inlines object IDs only after `int()` conversion.
- Pickle is used only once, to read the user's own v3 file during migration.
