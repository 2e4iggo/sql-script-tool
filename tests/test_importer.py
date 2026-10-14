import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqltool.importer import (discover, read_frame, frame_rows, build_plan, column_check,
                              list_sheets)


def test_discover_skips_lock_files_and_other_exts(tmp_path):
    for name in ["a.csv", "b.xlsx", "~$b.xlsx", "c.txt", "D.CSV"]:
        (tmp_path / name).write_text("x\n1\n")
    names = [os.path.basename(p) for p in discover(str(tmp_path))]
    assert names == ["D.CSV", "a.csv", "b.xlsx"]


def test_read_csv_cleans_headers_and_keeps_strings(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text(" Id ,Name,,Code\n001,Ann,,X\n", encoding="utf-8-sig")
    df = read_frame(str(p))
    assert list(df.columns) == ["Id", "Name", "Code"]
    assert df.iloc[0, 0] == "001"           # leading zeros preserved


def test_frame_rows_null_handling():
    df = pd.DataFrame({"a": ["1", "", "NULL", " "], "b": ["x", "y", "null", ""]})
    assert frame_rows(df) == [["1", "x"], [None, "y"]]


def test_build_plan_multi_sheet_names(tmp_path):
    p = tmp_path / "Book.xlsx"
    with pd.ExcelWriter(p) as w:
        pd.DataFrame({"a": [1, 2]}).to_excel(w, sheet_name="One", index=False)
        pd.DataFrame({"b": [3]}).to_excel(w, sheet_name="Two", index=False)
    single = tmp_path / "Single.csv"
    single.write_text("c\n5\n")
    assert list_sheets(str(p)) == ["One", "Two"]
    plan = build_plan([str(p), str(single)], schema="stg", mode="replace")
    assert [i.table for i in plan] == ["Book_One", "Book_Two", "Single"]
    assert [i.rows for i in plan] == [2, 1, 1]
    assert all(i.schema == "stg" and i.mode == "replace" and i.status == "ready" for i in plan)


def test_build_plan_reports_bad_file(tmp_path):
    p = tmp_path / "bad.xlsx"
    p.write_text("not really excel")
    plan = build_plan([str(p)])
    assert plan[0].status == "error" and plan[0].error


def test_column_check_case_insensitive():
    missing, extra = column_check(["Id", "Name", "Created"], ["id", "NAME", "Email"])
    assert missing == ["Email"]
    assert extra == ["Created"]
