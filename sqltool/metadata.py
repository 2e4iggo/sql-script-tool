"""Catalog queries -> plain dataclasses. All queries are parameterized."""
from dataclasses import dataclass, field

TYPE_INFO = {
    # code: (category, label)
    "U":  ("Tables", "Table"),
    "V":  ("Views", "View"),
    "P":  ("Procedures", "Procedure"),
    "FN": ("Functions", "Scalar function"),
    "IF": ("Functions", "Inline table function"),
    "TF": ("Functions", "Table function"),
    "FS": ("Functions", "CLR scalar function"),
    "FT": ("Functions", "CLR table function"),
    "TR": ("Triggers", "Trigger"),
}
CATEGORIES = ["Tables", "Views", "Procedures", "Functions", "Triggers"]
FUNCTION_TYPES = {"FN", "IF", "TF", "FS", "FT"}


@dataclass
class ObjectInfo:
    object_id: int
    schema: str
    name: str
    type: str
    modified: object = None

    @property
    def category(self):
        return TYPE_INFO.get(self.type, ("Other", self.type))[0]

    @property
    def full_name(self):
        return f"{self.schema}.{self.name}"


@dataclass
class ColumnMeta:
    name: str
    type_name: str
    max_length: int = 0
    precision: int = 0
    scale: int = 0
    nullable: bool = True
    is_identity: bool = False
    seed: str = "1"
    increment: str = "1"
    computed: str = None
    persisted: bool = False
    default_name: str = None
    default_def: str = None
    user_type_schema: str = None     # set for user-defined alias types


@dataclass
class IndexMeta:
    name: str
    type_desc: str                   # CLUSTERED / NONCLUSTERED / ...
    is_pk: bool = False
    is_unique_constraint: bool = False
    is_unique: bool = False
    filter: str = None
    data_space: str = None
    keys: list = field(default_factory=list)       # [(column, is_desc)]
    includes: list = field(default_factory=list)


@dataclass
class ForeignKeyMeta:
    name: str
    ref_schema: str
    ref_table: str
    columns: list = field(default_factory=list)
    ref_columns: list = field(default_factory=list)
    on_delete: str = "NO_ACTION"
    on_update: str = "NO_ACTION"
    disabled: bool = False


@dataclass
class CheckMeta:
    name: str
    definition: str
    disabled: bool = False


@dataclass
class TableMeta:
    schema: str
    name: str
    columns: list = field(default_factory=list)
    indexes: list = field(default_factory=list)
    foreign_keys: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    data_space: str = "PRIMARY"

    @property
    def primary_key(self):
        return next((i for i in self.indexes if i.is_pk), None)


# ─────────────────────────────────────────────────────────────────
#  QUERIES
# ─────────────────────────────────────────────────────────────────

_TYPES_SQL = ", ".join(f"'{t}'" for t in TYPE_INFO)


def list_objects(db):
    rows = db.query(f"""
        SELECT o.object_id, s.name, o.name, RTRIM(o.type), o.modify_date
        FROM sys.objects o
        JOIN sys.schemas s ON s.schema_id = o.schema_id
        WHERE o.type IN ({_TYPES_SQL}) AND o.is_ms_shipped = 0
        ORDER BY s.name, o.name""")
    return [ObjectInfo(r[0], r[1], r[2], r[3], r[4]) for r in rows]


def resolve_object(db, text):
    """Find an object from user text: name, schema.name or [schema].[name]."""
    text = text.strip()
    rows = db.query(f"""
        SELECT TOP (2) o.object_id, s.name, o.name, RTRIM(o.type), o.modify_date
        FROM sys.objects o
        JOIN sys.schemas s ON s.schema_id = o.schema_id
        WHERE o.type IN ({_TYPES_SQL})
          AND o.name = PARSENAME(?, 1)
          AND (PARSENAME(?, 2) IS NULL OR s.name = PARSENAME(?, 2))
        ORDER BY CASE WHEN s.name = 'dbo' THEN 0 ELSE 1 END, s.name""",
        (text, text, text))
    return [ObjectInfo(r[0], r[1], r[2], r[3], r[4]) for r in rows]


def get_definition(db, object_id):
    return db.scalar("SELECT OBJECT_DEFINITION(?)", (object_id,))


def get_dependencies(db, object_ids):
    """Edges (referencing_id, referenced_id) among the given objects."""
    ids = sorted({int(i) for i in object_ids})
    if len(ids) < 2:
        return []
    id_list = ",".join(str(i) for i in ids)      # ints only, safe to inline
    rows = db.query(f"""
        SELECT DISTINCT referencing_id, referenced_id
        FROM sys.sql_expression_dependencies
        WHERE referencing_id IN ({id_list}) AND referenced_id IN ({id_list})
          AND referencing_id <> referenced_id
        UNION
        SELECT DISTINCT parent_object_id, referenced_object_id
        FROM sys.foreign_keys
        WHERE parent_object_id IN ({id_list}) AND referenced_object_id IN ({id_list})
          AND parent_object_id <> referenced_object_id""")
    return [(r[0], r[1]) for r in rows]


def get_table_meta(db, obj):
    oid = obj.object_id
    t = TableMeta(schema=obj.schema, name=obj.name)

    for r in db.query("""
        SELECT c.name, t.name, t.is_user_defined, SCHEMA_NAME(t.schema_id),
               c.max_length, c.precision, c.scale, c.is_nullable, c.is_identity,
               CONVERT(nvarchar(40), ic.seed_value), CONVERT(nvarchar(40), ic.increment_value),
               cc.definition, cc.is_persisted, dc.name, dc.definition
        FROM sys.columns c
        JOIN sys.types t ON t.user_type_id = c.user_type_id
        LEFT JOIN sys.identity_columns ic ON ic.object_id = c.object_id AND ic.column_id = c.column_id
        LEFT JOIN sys.computed_columns cc ON cc.object_id = c.object_id AND cc.column_id = c.column_id
        LEFT JOIN sys.default_constraints dc ON dc.parent_object_id = c.object_id
                                            AND dc.parent_column_id = c.column_id
        WHERE c.object_id = ?
        ORDER BY c.column_id""", (oid,)):
        t.columns.append(ColumnMeta(
            name=r[0], type_name=r[1], user_type_schema=r[3] if r[2] else None,
            max_length=r[4], precision=r[5], scale=r[6], nullable=bool(r[7]),
            is_identity=bool(r[8]), seed=r[9] or "1", increment=r[10] or "1",
            computed=r[11], persisted=bool(r[12]), default_name=r[13], default_def=r[14]))

    by_name = {}
    for r in db.query("""
        SELECT i.name, i.type_desc, i.is_primary_key, i.is_unique_constraint, i.is_unique,
               i.filter_definition, ds.name, COL_NAME(ic.object_id, ic.column_id),
               ic.is_descending_key, ic.is_included_column
        FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        LEFT JOIN sys.data_spaces ds ON ds.data_space_id = i.data_space_id
        WHERE i.object_id = ? AND i.type > 0 AND i.is_hypothetical = 0
        ORDER BY i.index_id, ic.is_included_column, ic.key_ordinal, ic.index_column_id""", (oid,)):
        idx = by_name.get(r[0])
        if idx is None:
            idx = by_name[r[0]] = IndexMeta(
                name=r[0], type_desc=r[1], is_pk=bool(r[2]), is_unique_constraint=bool(r[3]),
                is_unique=bool(r[4]), filter=r[5], data_space=r[6])
            t.indexes.append(idx)
        if r[9]:
            idx.includes.append(r[7])
        else:
            idx.keys.append((r[7], bool(r[8])))

    space = db.scalar("""
        SELECT ds.name FROM sys.indexes i
        JOIN sys.data_spaces ds ON ds.data_space_id = i.data_space_id
        WHERE i.object_id = ? AND i.index_id < 2""", (oid,))
    if space:
        t.data_space = space

    fks = {}
    for r in db.query("""
        SELECT fk.name, SCHEMA_NAME(rt.schema_id), rt.name,
               COL_NAME(fkc.parent_object_id, fkc.parent_column_id),
               COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id),
               fk.delete_referential_action_desc, fk.update_referential_action_desc, fk.is_disabled
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
        JOIN sys.objects rt ON rt.object_id = fk.referenced_object_id
        WHERE fk.parent_object_id = ?
        ORDER BY fk.name, fkc.constraint_column_id""", (oid,)):
        fk = fks.get(r[0])
        if fk is None:
            fk = fks[r[0]] = ForeignKeyMeta(name=r[0], ref_schema=r[1], ref_table=r[2],
                                            on_delete=r[5], on_update=r[6], disabled=bool(r[7]))
            t.foreign_keys.append(fk)
        fk.columns.append(r[3])
        fk.ref_columns.append(r[4])

    for r in db.query("""
        SELECT name, definition, is_disabled FROM sys.check_constraints
        WHERE parent_object_id = ? ORDER BY name""", (oid,)):
        t.checks.append(CheckMeta(name=r[0], definition=r[1], disabled=bool(r[2])))

    return t


def get_table_columns(db, schema, table):
    """Column names of an existing table, or None if it doesn't exist."""
    oid = db.scalar("SELECT OBJECT_ID(QUOTENAME(?) + '.' + QUOTENAME(?), N'U')", (schema, table))
    if oid is None:
        return None
    return [r[0] for r in db.query(
        "SELECT name FROM sys.columns WHERE object_id = ? ORDER BY column_id", (oid,))]
