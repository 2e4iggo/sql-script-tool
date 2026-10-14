"""SQL Script Tool v4 — launcher. Code lives in the sqltool package next to this file.

Requires: pip install ttkbootstrap keyring pyodbc pandas openpyxl
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def selftest(report_path):
    """Check the bundled dependencies load (used to verify the PyInstaller build)."""
    lines = []
    for name, check in [
        ("pyodbc drivers", lambda: __import__("pyodbc").drivers()),
        ("keyring backend", lambda: type(__import__("keyring").get_keyring()).__name__),
        ("pandas", lambda: __import__("pandas").__version__),
        ("openpyxl", lambda: __import__("openpyxl").__version__),
        ("ttkbootstrap", lambda: __import__("ttkbootstrap").__name__),
        ("sqltool", lambda: __import__("sqltool.app", fromlist=["App"]).App.__name__),
        ("icon", lambda: os.path.exists(os.path.join(getattr(sys, "_MEIPASS", ""), "assets", "app.ico"))),
    ]:
        try:
            lines.append(f"OK   {name}: {check()}")
        except Exception as e:
            lines.append(f"FAIL {name}: {e!r}")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2])
        sys.exit(0)
    try:
        from sqltool.app import main
    except ImportError as e:
        # Show the problem instead of a console window that flashes and closes.
        import tkinter as tk
        from tkinter import messagebox
        tk.Tk().withdraw()
        messagebox.showerror(
            "SQL Script Tool — missing package",
            f"{e}\n\nThis Python: {sys.executable}\n\n"
            f"Install the packages for this Python:\n"
            f"\"{sys.executable}\" -m pip install ttkbootstrap keyring pyodbc pandas openpyxl\n\n"
            "Or start the app with 'Run SQL Script Tool.bat'.")
        sys.exit(1)
    main()
