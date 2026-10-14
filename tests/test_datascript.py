import datetime as dt
import os
import sys
import uuid
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqltool.datascript import validate_select, guess_target, plan_columns, table_text, select_all_sql
from sqltool.metadata import TableMeta, ColumnMeta
from sqltool.scripting import sql_literal, ident, insert_statement


# ── literals ─────────────────────────────────────────────────────

@pytest.mark.parametrize("value, expected", [
    (None, "NULL"),
    ("ACME", "N'ACME'"),
    ("O'Brien", "N'O''Brien'"),
    ("", "N''"),
    ("Bé 中文", "N'Bé 中文'"),
    (50, "50"),
    (-7, "-7"),
    (True, "1"),
    (False, "0"),
    (Decimal("2500.00"), "2500.00"),
    (Decimal("1E+2"), "100"),
    (Decimal("0.000001"), "0.000001"),
    (1.5, "1.5"),
    (dt.datetime(1990, 1, 1), "'19900101 00:00:00'"),
    (dt.datetime(2026, 8, 19, 11, 31, 9), "'20260819 11:31:09'"),
    (dt.datetime(2026, 8, 19, 11, 31, 9, 123000), "'20260819 11:31:09.123'"),
    (dt.datetime(2026, 8, 19, 11, 31, 9, 123456), "'20260819 11:31:09.123456'"),
    (dt.date(2036, 1, 1), "'20360101'"),
    (dt.time(8, 30), "'08:30:00'"),
    (b"\x00\xab", "0x00AB"),
    (uuid.UUID("12345678-1234-5678-1234-567812345678"), "N'12345678-1234-5678-1234-567812345678'"),
])
def test_sql_literal(value, expected):
    assert sql_literal(value) == expected


def test_ident():
    assert ident("EMP_ID") == "EMP_ID"
    assert ident("Order") == "[Order]"
    assert ident("First Name") == "[First Name]"
    assert ident("1abc") == "[1abc]"
    assert ident("a]b") == "[a]]b]"


def test_insert_statement_matches_sample_style():
    s = insert_statement("EMPLOYEE", ["COMP_CODE", "EMP_ID", "DOC_TYPE", "BIRTH_DATE", "AGE"],
                         ["ACME", "1001", None, dt.datetime(1990, 1, 1), 36])
    assert s == ("INSERT INTO EMPLOYEE (COMP_CODE,EMP_ID,DOC_TYPE,BIRTH_DATE,AGE)\n"
                 "VALUES (N'ACME',N'1001',NULL,'19900101 00:00:00',36)")


# ── validation ───────────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "SELECT * FROM EMPLOYEE WHERE EMP_ID='1001'",
    "  select * from dbo.T;  ",
    "-- comment\nSELECT a FROM T /* DELETE */ WHERE b = 'UPDATE x; DROP TABLE y'",
    "WITH c AS (SELECT * FROM T) SELECT * FROM c",
    "SELECT [Update], [Into] FROM T",
])
def test_validate_accepts(sql):
    validate_select(sql)


@pytest.mark.parametrize("sql, msg", [
    ("", "Enter"),
    ("UPDATE T SET a = 1", "Only SELECT"),
    ("SELECT * FROM T; DROP TABLE T", "one statement"),
    ("SELECT * INTO X FROM T", "INTO"),
    ("WITH c AS (SELECT * FROM T) DELETE FROM c", "DELETE"),
    ("EXEC sp_who", "Only SELECT"),
])
def test_validate_rejects(sql, msg):
    with pytest.raises(ValueError, match=msg):
        validate_select(sql)


# ── target guessing ──────────────────────────────────────────────

@pytest.mark.parametrize("sql, target, check", [
    ("SELECT * FROM EMPLOYEE WHERE EMP_ID='1001'", "EMPLOYEE", False),
    ("select * from dbo . EMPLOYEE e", "dbo.EMPLOYEE", False),
    ("SELECT * FROM [dbo].[My Table]", "[dbo].[My Table]", False),
    ("SELECT a.* FROM A a JOIN B b ON a.id = b.id", "A", True),
    ("SELECT * FROM A, B", "A", True),
    ("WITH c AS (SELECT * FROM T) SELECT * FROM c", "T", True),
    ("SELECT 1 AS x", None, False),
    ("SELECT 'FROM fake' AS x FROM Real", "Real", False),
])
def test_guess_target(sql, target, check):
    assert guess_target(sql) == (target, check)


# ── column planning ──────────────────────────────────────────────

def test_plan_columns_skips_computed_and_rowversion_and_flags_identity():
    meta = TableMeta(schema="dbo", name="T", columns=[
        ColumnMeta("Id", "int", is_identity=True),
        ColumnMeta("Name", "nvarchar"),
        ColumnMeta("Total", "decimal", computed="([a]*2)"),
        ColumnMeta("RV", "timestamp"),
    ])
    p = plan_columns(["id", "Name", "Total", "RV"], meta)
    assert p.names == ["Id", "Name"]          # real column casing
    assert p.keep == [0, 1]
    assert p.skipped == ["Total", "RV"]
    assert p.identity and not p.unknown


def test_plan_columns_unknown_and_duplicates():
    meta = TableMeta(schema="dbo", name="T", columns=[ColumnMeta("A", "int")])
    p = plan_columns(["A", "Alias", "a"], meta)
    assert p.unknown == ["Alias"]
    assert p.duplicates == ["a"]


def test_plan_columns_without_meta_keeps_all():
    p = plan_columns(["x", "y"], None)
    assert p.names == ["x", "y"] and p.keep == [0, 1]


def test_table_text_and_select_all():
    assert table_text("dbo", "EMPLOYEE") == "EMPLOYEE"
    assert table_text("hr", "My Table") == "hr.[My Table]"
    assert select_all_sql("dbo", "EMPLOYEE") == "SELECT * FROM EMPLOYEE"
