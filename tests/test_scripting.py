import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqltool.metadata import (ObjectInfo, TableMeta, ColumnMeta, IndexMeta,
                              ForeignKeyMeta, CheckMeta)
from sqltool.scripting import (ScriptOptions, build_module_script, build_table_script,
                               format_type, order_objects, compact, to_create_or_alter,
                               SEPARATOR, safe_filename)


def col(name, t, **kw):
    return ColumnMeta(name=name, type_name=t, **kw)


# ── format_type ──────────────────────────────────────────────────

def test_format_type_lengths():
    assert format_type(col("a", "varchar", max_length=50)) == "VARCHAR(50)"
    assert format_type(col("a", "varchar", max_length=-1)) == "VARCHAR(MAX)"
    assert format_type(col("a", "nvarchar", max_length=100)) == "NVARCHAR(50)"
    assert format_type(col("a", "nchar", max_length=20)) == "NCHAR(10)"
    assert format_type(col("a", "nvarchar", max_length=-1)) == "NVARCHAR(MAX)"
    assert format_type(col("a", "char", max_length=3)) == "CHAR(3)"
    assert format_type(col("a", "varbinary", max_length=-1)) == "VARBINARY(MAX)"


def test_format_type_varchar_to_nvarchar():
    assert format_type(col("a", "varchar", max_length=50), True) == "NVARCHAR(50)"
    assert format_type(col("a", "varchar", max_length=8000), True) == "NVARCHAR(MAX)"
    assert format_type(col("a", "varchar", max_length=-1), True) == "NVARCHAR(MAX)"
    assert format_type(col("a", "char", max_length=3), True) == "CHAR(3)"


def test_format_type_precision_scale():
    assert format_type(col("a", "decimal", precision=18, scale=2)) == "DECIMAL(18,2)"
    assert format_type(col("a", "numeric", precision=10, scale=0)) == "NUMERIC(10,0)"
    assert format_type(col("a", "datetime2", scale=3)) == "DATETIME2(3)"
    assert format_type(col("a", "time", scale=7)) == "TIME(7)"
    assert format_type(col("a", "datetime")) == "DATETIME"
    assert format_type(col("a", "int")) == "INT"
    assert format_type(col("a", "float", precision=53)) == "FLOAT"
    assert format_type(col("a", "MyType", user_type_schema="dbo")) == "[dbo].[MyType]"


# ── tables ───────────────────────────────────────────────────────

def sample_table():
    return TableMeta(
        schema="dbo", name="Orders",
        columns=[
            col("Id", "int", nullable=False, is_identity=True, seed="1", increment="1"),
            col("Region", "varchar", max_length=10, nullable=False),
            col("Amount", "decimal", precision=18, scale=2, default_name="DF_Orders_Amount",
                default_def="((0))"),
            col("Total", "decimal", computed="([Amount]*(2))", persisted=True),
        ],
        indexes=[
            IndexMeta(name="PK_Orders", type_desc="CLUSTERED", is_pk=True, is_unique=True,
                      data_space="PRIMARY", keys=[("Region", False), ("Id", True)]),
            IndexMeta(name="IX_Amount", type_desc="NONCLUSTERED", data_space="PRIMARY",
                      keys=[("Amount", False)], includes=["Region"]),
        ],
        foreign_keys=[ForeignKeyMeta(name="FK_Orders_Region", ref_schema="ref", ref_table="Region",
                                     columns=["Region"], ref_columns=["Code"], on_delete="CASCADE")],
        checks=[CheckMeta(name="CK_Amount", definition="([Amount]>=(0))")],
    )


def test_table_script_columns_in_order_and_types():
    s = build_table_script(sample_table(), ScriptOptions())
    lines = s.splitlines()
    assert lines[0].startswith("IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[Orders]')")
    assert "CREATE TABLE [dbo].[Orders] (" in s
    body = [l.strip() for l in lines]
    i = body.index("[Id] INT IDENTITY(1,1) NOT NULL,")
    assert body[i + 1] == "[Region] NVARCHAR(10) NOT NULL,"
    assert body[i + 2] == "[Amount] DECIMAL(18,2) NULL CONSTRAINT [DF_Orders_Amount] DEFAULT ((0)),"
    assert body[i + 3] == "[Total] AS ([Amount]*(2)) PERSISTED,"
    assert "CONSTRAINT [PK_Orders] PRIMARY KEY CLUSTERED ([Region] ASC, [Id] DESC)" in s
    assert ") ON [PRIMARY]" in s
    assert lines[-1] == SEPARATOR
    # optional sections off by default
    assert "IX_Amount" not in s and "FOREIGN KEY" not in s and "CK_Amount" not in s


def test_table_script_last_item_has_no_trailing_comma():
    s = build_table_script(sample_table(), ScriptOptions())
    pk_line = next(l for l in s.splitlines() if "PRIMARY KEY" in l)
    assert not pk_line.rstrip().endswith(",")


def test_table_script_optional_sections():
    opts = ScriptOptions(table_indexes=True, table_foreign_keys=True, table_check_constraints=True,
                         table_if_not_exists=False, varchar_to_nvarchar=False)
    s = build_table_script(sample_table(), opts)
    assert s.startswith("CREATE TABLE [dbo].[Orders] (")
    assert "[Region] VARCHAR(10) NOT NULL" in s
    assert "CONSTRAINT [CK_Amount] CHECK ([Amount]>=(0))" in s
    assert "CREATE NONCLUSTERED INDEX [IX_Amount] ON [dbo].[Orders] ([Amount] ASC) INCLUDE ([Region])" in s
    assert "FOREIGN KEY ([Region]) REFERENCES [ref].[Region] ([Code]) ON DELETE CASCADE" in s


def test_table_script_separate_fks():
    opts = ScriptOptions(table_foreign_keys=True)
    script, fks = build_table_script(sample_table(), opts, separate_fks=True)
    assert "FOREIGN KEY" not in script
    assert "FOREIGN KEY" in fks


def test_quoting_names_with_brackets_and_quotes():
    t = TableMeta(schema="dbo", name="Odd]Name's", columns=[col("x", "int")])
    s = build_table_script(t, ScriptOptions())
    assert "OBJECT_ID(N'[dbo].[Odd]]Name''s]')" in s
    assert "CREATE TABLE [dbo].[Odd]]Name's] (" in s


# ── modules ──────────────────────────────────────────────────────

VIEW = ObjectInfo(1, "dbo", "vOrders", "V")
PROC = ObjectInfo(2, "sales", "uspGet", "P")
SCALAR = ObjectInfo(3, "dbo", "fnTax", "FN")
TVF = ObjectInfo(4, "dbo", "fnRows", "IF")


def test_view_script_matches_v3_layout():
    s = build_module_script(VIEW, "\nCREATE VIEW dbo.vOrders AS SELECT 1 AS x\n", ScriptOptions())
    assert s == (
        "IF EXISTS (SELECT * FROM dbo.sysobjects WHERE id = OBJECT_ID(N'[dbo].[vOrders]')"
        " AND OBJECTPROPERTY(id, N'IsView') = 1)\n    DROP VIEW [dbo].[vOrders]\nGO\n"
        "CREATE VIEW dbo.vOrders AS SELECT 1 AS x\n"
        "GO\nGRANT SELECT ON [dbo].[vOrders] TO SDA_ROLE\nGO\n"
        "GRANT SELECT ON [dbo].[vOrders] TO HR_ROLE\nGO\n" + SEPARATOR)


def test_grant_verbs_and_schema():
    p = build_module_script(PROC, "CREATE PROCEDURE sales.uspGet AS SELECT 1", ScriptOptions())
    assert "DROP PROCEDURE [sales].[uspGet]" in p and "GRANT EXEC ON [sales].[uspGet] TO SDA_ROLE" in p
    f = build_module_script(SCALAR, "CREATE FUNCTION dbo.fnTax() RETURNS INT AS BEGIN RETURN 1 END",
                            ScriptOptions())
    assert "GRANT EXEC ON [dbo].[fnTax]" in f
    t = build_module_script(TVF, "CREATE FUNCTION dbo.fnRows() RETURNS TABLE AS RETURN SELECT 1 x",
                            ScriptOptions())
    assert "GRANT SELECT ON [dbo].[fnRows]" in t


def test_custom_roles_and_no_grants():
    s = build_module_script(VIEW, "CREATE VIEW v AS SELECT 1", ScriptOptions(grant_roles=["APP"]))
    assert "TO APP" in s and "SDA_ROLE" not in s
    s = build_module_script(VIEW, "CREATE VIEW v AS SELECT 1",
                            ScriptOptions(include_grants=False, include_separator=False))
    assert "GRANT" not in s and s.endswith("SELECT 1\nGO")


def test_create_or_alter_mode():
    d = "-- header\n/* block */\ncreate   VIEW dbo.v AS SELECT 'CREATE' AS c"
    out = to_create_or_alter(d)
    assert out == "-- header\n/* block */\nCREATE OR ALTER   VIEW dbo.v AS SELECT 'CREATE' AS c"
    assert to_create_or_alter("CREATE OR ALTER VIEW v AS SELECT 1") == "CREATE OR ALTER VIEW v AS SELECT 1"
    s = build_module_script(VIEW, "CREATE VIEW v AS SELECT 1", ScriptOptions(header_mode="create_or_alter"))
    assert "DROP VIEW" not in s and s.startswith("CREATE OR ALTER VIEW")


def test_definition_mode():
    s = build_module_script(VIEW, "CREATE VIEW v AS SELECT 1", ScriptOptions(header_mode="definition"))
    assert s == "CREATE VIEW v AS SELECT 1\nGO\n" + SEPARATOR


# ── ordering / misc ──────────────────────────────────────────────

def test_order_objects_dependencies_first():
    t = ObjectInfo(10, "dbo", "Z_Table", "U")
    v1 = ObjectInfo(11, "dbo", "A_View", "V")
    v2 = ObjectInfo(12, "dbo", "B_View", "V")     # A_View depends on B_View
    p = ObjectInfo(13, "dbo", "Proc", "P")
    f = ObjectInfo(14, "dbo", "Fn", "IF")         # Fn depends on A_View
    out = order_objects([p, v1, f, v2, t], edges=[(11, 12), (14, 11), (11, 10)])
    names = [o.name for o in out]
    assert names.index("Z_Table") < names.index("B_View") < names.index("A_View") < names.index("Fn")
    assert names[0] == "Z_Table"


def test_order_objects_cycle_does_not_drop():
    a = ObjectInfo(1, "dbo", "a", "V")
    b = ObjectInfo(2, "dbo", "b", "V")
    assert {o.name for o in order_objects([a, b], edges=[(1, 2), (2, 1)])} == {"a", "b"}


def test_compact_matches_v3():
    assert compact("  a\n\n    b  \n\t\nc") == "a\nb\nc"


def test_safe_filename():
    assert safe_filename("dbo.Name:1?") == "dbo.Name_1_"
