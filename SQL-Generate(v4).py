"""SQL Script Tool v4 — launcher. Code lives in the sqltool package next to this file.

Requires: pip install ttkbootstrap keyring pyodbc pandas openpyxl
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
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
