# Changelog

## 4.1 (2026-10-14): Data → INSERT

### Added
- **Data → INSERT**: run a SELECT and get one `INSERT INTO … VALUES (…)` per row, in the same style as the hand-written scripts:
  - bare column names, `N'…'` text
  - `'YYYYMMDD HH:MM:SS'` dates
  - Opened from the toolbar, Ctrl+Shift+D, or right-click a table → *Script data (INSERT)…*
- Full date/time precision: `DATETIME2(7)` and `DATETIMEOFFSET` included. Verified by a round trip (script → delete → re-run → `EXCEPT` = 0 rows).
- Computed and rowversion columns are skipped. `SET IDENTITY_INSERT` is added automatically when the identity column is included.
- Read-only guard: only a single SELECT / WITH is accepted, and the query is always rolled back.
- Output to the editor (≤ 20,000 rows) or streamed to a file (any size), with Cancel.

## 4.0 (2026-10-14): full rewrite of `SQL-Generate(v3).py`

### Script output differences from v3

Check these before using v4 output in an existing deployment process:

| Area | v3 | v4 |
|---|---|---|
| DECIMAL | `DECIMAL` (SQL Server treats it as `DECIMAL(18,0)`, so **scale is lost**) | `DECIMAL(p,s)` |
| CHAR / NCHAR / VARBINARY / DATETIME2 / TIME | no length / scale | correct length / scale |
| NVARCHAR length | from INFORMATION_SCHEMA (chars) | from sys.columns (bytes / 2), same result |
| VARCHAR(>4000) with conversion | `NVARCHAR(8000)` (invalid) | `NVARCHAR(MAX)` |
| Column order | not guaranteed (no ORDER BY) | `column_id` order |
| PK name | always `{table}_PK` | the real constraint name |
| PK column order / direction | not guaranteed, always ASC | `key_ordinal` order, ASC/DESC kept |
| Table name in CREATE | `CREATE TABLE name` | `CREATE TABLE [schema].[name]` |
| Schema | always `dbo` | the object's real schema |
| Identity, defaults, computed columns | missing | included |
| Unique constraints | missing | included |
| Indexes, FKs, check constraints | missing | optional |
| Scalar function grant | `GRANT SELECT` (rejected by SQL Server) | `GRANT EXEC` |
| Separator line | `────…` (bare text, a syntax error if run) | `-- ────…` (SQL comment) |
| Grant roles | hard-coded `SDA_ROLE`, `HR_ROLE` | configurable (same defaults) |

These are unchanged: the v3 drop-header text, the `GO` placement, VARCHAR→NVARCHAR conversion (now a toggle, on by default) and compact copy.

### Fixed

- **SQL injection:** object and table names were pasted into SQL with f-strings. All lookups now use parameters.
- **Plaintext passwords** in `~/conn_details.pkl`: they now go to Windows Credential Manager. The old file is migrated and renamed to `.bak`.
- **Changed passwords were never saved:** v3's duplicate check skipped the save.
- **Username and password were wiped** when picking a database from the Auto-fill list.
- **Passwords with leading or trailing spaces were trimmed.**
- **The UI froze during database work, and clicks could pile up:** work now runs in background threads with a busy state.
- **Every action opened a new connection:** v4 keeps one connection per session.
- **Import:** v3 read only the first sheet, used slow row-by-row inserts, and had no way to replace or truncate.

### Added

- Object browser with search and type filters, and multi-select.
- Batch generation in dependency order. Save as one `.sql` file or one file per object.
- Header modes: DROP + CREATE, CREATE OR ALTER, definition only.
- Triggers.
- Database switcher in the workspace.
- Windows authentication, driver selection, Encrypt / Trust certificate options, connection aliases, Test button.
- Import:
  - choose files or a folder
  - every sheet, editable target per file
  - four modes
  - preview and column check
  - progress bar and Cancel
  - fast bulk insert
- SQL syntax highlighting and line numbers.
- Dark and light themes.
- Keyboard shortcuts and a log panel.
- Settings dialog.
- Unit tests (`tests/`).
