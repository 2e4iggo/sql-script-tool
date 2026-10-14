# SQL Script Tool v4

A desktop tool for SQL Server that:

- generates deployment scripts (DROP / CREATE / GRANT) for tables, views, stored procedures, functions and triggers
- imports Excel / CSV files into tables

## Quick start

Double-click **`Run SQL Script Tool.bat`**.

Or from a terminal:

```
cd D:\Python\App\SQL-Generate-v4
python "SQL-Generate(v4).py"
```

> Double-clicking `SQL-Generate(v4).py` directly opens it with Python 3.13 on this PC. Python 3.13 doesn't have the required packages, so use the `.bat` file. The `.bat` always uses `C:\Python314\pythonw.exe`.

## Requirements

- Python 3.12+ (developed on 3.14)
- An ODBC driver for SQL Server. *ODBC Driver 17/18 for SQL Server* is auto-detected.
- Packages:

```
pip install -r requirements.txt
```

## Using it

### 1. Connect

- **Saved connections** are listed on the left.
  - Double-click to connect.
  - **Del** removes the selected one.
  - The search box filters the list.
- **Connection form** fields:
  - Server, authentication (SQL Server or Windows), username and password
  - Database: click **⟳ Load** to list the databases on the server
- **Test** checks the login without opening the workspace.
- **Save** stores the connection.
- **Connect** saves it and opens the workspace.
- Passwords are stored in **Windows Credential Manager**, under the name `SQLScriptTool`. They are never written to disk by the app.

### 2. Generate scripts

1. Find objects in the **Objects** list on the left.
   - Type in the filter box. Words can appear in any order, e.g. `staff hrm`.
   - Use the type buttons to show or hide Tables, Views, Procs, Funcs and Trig.
2. Select one object, or several with Ctrl/Shift-click. Clicking a group header selects the whole group.
3. Press **Generate**. Double-click and Enter also generate.
   - Typing an exact name in the filter and pressing Enter generates it immediately, like v3.
   - Several objects are scripted in dependency order: tables first, then functions, views and procedures. Foreign keys come last.
4. Adjust the output with the toolbar options:
   - **Header**:
     - `DROP + CREATE` is the v3 format.
     - `CREATE OR ALTER`
     - `Definition only`
   - **Grants**: adds `GRANT SELECT/EXEC … TO <role>`. Change the roles in **Settings**.
   - **Separator**: adds a `-- ─────` comment line after each script.
   - **Table options**:
     - IF NOT EXISTS wrapper
     - VARCHAR→NVARCHAR conversion
     - indexes, foreign keys, check constraints
5. **Copy** puts the script on the clipboard in compact form: indentation and blank lines are removed, as in v3. Turn this off in Settings.
6. **Save .sql** writes the script to a file. If you generated several objects, it asks: one combined file, or one file per object.

You can switch database from the **Database** dropdown at the top without going back to the connect screen.

### 3. Import Excel / CSV

Open it from **📂 Import data…** (or Ctrl+I).

1. **+ Files…** or **+ Folder…**: each CSV and each Excel *sheet* becomes one row.
   - Single-sheet files go to a table named after the file.
   - Workbooks with several sheets use `file_sheet`.
2. Select a row to see a **preview** of the first 50 rows and a **target check**. The check tells you whether the table will be created, dropped, or which columns don't match.
3. Change the target with **Target table** + **Set**. Change schema / mode for selected rows with **Apply to selected**.
4. **▶ Run import**. Each file runs in its own transaction. **Cancel** rolls back the current file.

| Mode | Table missing | Table exists |
|---|---|---|
| Create if missing + append (default) | created | rows appended |
| Replace | created | **dropped** and recreated |
| Truncate + insert | error | emptied, then filled |
| Append only | error | rows appended |

How data is stored:
- New tables use `NVARCHAR(MAX)` columns.
- Empty cells and the text `NULL` become NULL.
- Fully empty rows are skipped.
- Values are read as text, so leading zeros are kept.

## Keyboard shortcuts

| Key | Action |
|---|---|
| Ctrl+Enter | Generate |
| Ctrl+Shift+C | Copy script |
| Ctrl+S | Save script |
| Ctrl+F | Focus object filter |
| F5 | Refresh object list |
| Ctrl+I | Import data |
| Ctrl+L | Show / hide log |

## Where things are stored

| What | Where |
|---|---|
| Settings (grant roles, options, theme, window size) | `%APPDATA%\SQLScriptTool\settings.json` |
| Saved connections (no passwords) | `%APPDATA%\SQLScriptTool\connections.json` |
| Passwords | Windows Credential Manager → `SQLScriptTool` |
| Old v3 connections (after migration) | `%USERPROFILE%\conn_details.pkl.bak` |

On first start, v4 imports v3's `conn_details.pkl` automatically, then renames it to `.bak`.

## Troubleshooting

- **Double-click does nothing / a window flashes:** use `Run SQL Script Tool.bat`, or install the packages for the Python that opened it. The app shows a message with the exact command.
- **Login failed with Windows authentication:** the server may only allow SQL logins. Use SQL Server authentication.
- **SSL / certificate errors (ODBC Driver 18):** keep *Trust server certificate* on, or turn *Encrypt* off.
- **"No definition available":** the object is encrypted, or your login lacks `VIEW DEFINITION`.

## Running the tests

```
cd D:\Python\App\SQL-Generate-v4
python -m pytest tests -q
```

The tests don't need a database.

See [SPEC.md](SPEC.md) for the detailed behaviour, [CHANGELOG.md](CHANGELOG.md) for what changed from v3, and [CLAUDE.md](CLAUDE.md) for developer notes.
