# CLAUDE.md

Notes for AI assistants and developers working on this project.

## What this is

A Tkinter (ttkbootstrap) desktop app for SQL Server. It generates deployment scripts and imports Excel/CSV files into tables. It is a rewrite of `..\SQL-Generate(v3).py`, which stays as a reference and must not be edited.

- `SPEC.md` is the behaviour contract. Update it when behaviour changes.
- `CHANGELOG.md` records output differences from v3.

## Run and test

```
python "SQL-Generate(v4).py"          # or double-click "Run SQL Script Tool.bat"
python -m pytest tests -q              # no database needed
```

- **Two Pythons on this machine:** use `C:\Python314\python.exe`, which has the packages. Double-clicking a `.py` file runs `C:\Python313\python.exe`, which doesn't.
- **Local SQL Server:** the dev machine has a local instance. It accepts SQL logins only; Windows auth is rejected.
- **Test databases:**
  - The application databases on that server hold real HR data. Treat them as **read-only**.
  - Integration tests that create objects or import data must use **`tempdb`** and clean up afterwards.
  - Ask before writing anywhere else.

## Layout

```
SQL-Generate(v4).py   launcher (adds this folder to sys.path, friendly ImportError dialog)
sqltool/
  app.py              App: window, menu, log, status bar, App.run() job plumbing, theme
  settings.py         Settings dataclass -> %APPDATA%\SQLScriptTool\settings.json
  connections.py      ConnInfo, ConnectionStore (JSON + keyring), v3 .pkl migration
  db.py               Database: one pyodbc connection + RLock, query/scalar, driver detection
  metadata.py         catalog queries -> dataclasses (ObjectInfo, TableMeta, ColumnMeta, ...)
  scripting.py        PURE: metadata -> T-SQL text, ordering, compact(); no DB/UI imports
  importer.py         file discovery/reading/cleaning, build_plan, run_item
  worker.py           run_bg(widget, fn(job), ...) thread + queue; Job.check()/progress()
  ui/
    connect_screen.py   saved list + form
    workspace_screen.py object browser + editor + toolbar options
    import_dialog.py    plan grid, preview/check, run
    settings_dialog.py
    sql_text.py         Text + line-number gutter + regex highlighter
tests/                pytest; scripting + importer, no DB
```

## Rules and conventions

- **Keep `scripting.py` pure.** It takes metadata dataclasses and returns strings. Add unit tests for any output change. Generated scripts go into deployments, so byte-level changes matter. Record intentional ones in `CHANGELOG.md` and `SPEC.md`.
- **No string-built SQL with user input.** Use `?` parameters. For identifiers in generated DDL use `q()` / `qn()`; for literals inside `N'...'` use `lit()`.
- **Never block the Tk thread.** Wrap DB and file work in `app.run(fn, on_ok, label=...)`.
  - `fn(job)` runs in a thread and must not touch widgets.
  - Report progress with `job.progress(...)` and handle it in `on_progress` on the Tk thread.
  - Call `job.check()` in loops so Cancel works.
  - Only one `app.run` job runs at a time. Register buttons that must be disabled meanwhile with `app.register_busy(...)`.
- **Database access:**
  - Go through `Database.query()` / `scalar()`; they roll back afterwards.
  - For writes, hold `db.lock`, use `db.conn` directly, and commit or roll back yourself (see `importer.run_item`).
  - **Don't run DDL through `db.query()`.** Its trailing rollback undoes the DDL.
- **Lazy imports:** `pyodbc` and `pandas` are imported inside functions so the window appears fast. Keep it that way.
- **Settings:** add a field to the `Settings` dataclass with a default. Unknown or missing keys in old JSON files are handled automatically. If it is a script option, also add it to `ScriptOptions` with the same name; `from_settings` copies by name.
- **ttkbootstrap 2.x:**
  - Theme names are `bootstrap-dark` / `bootstrap-light`; the 1.x names like `darkly` are deprecated.
  - Use the `bootstyle="primary-outline"`-style strings.
  - `tb.Toplevel(title=..., transient=..., size=(w, h))`.
- **Style:** match the existing code: section banners `# ── name ───`, short docstrings, dataclasses, no type-hint noise.
- **Copy behaviour:** the user explicitly wants v3's compact copy (strip lines, drop blanks) as the default. Don't change it.

## Testing the UI

There are no automated UI tests in the repo. To smoke-test, drive `App` from a script:

1. Set `APPDATA`, `USERPROFILE` and `HOME` to a scratch folder **before importing `sqltool`**, so the real settings and the v3 `.pkl` aren't touched.
2. Chain steps with `root.after(...)`.
3. Take screenshots with `PIL.ImageGrab`.
4. Monkeypatch `tkinter.messagebox` so modal dialogs don't block.

Afterwards, delete any test secrets from keyring (`keyring.delete_password("SQLScriptTool", "server|user")`).
