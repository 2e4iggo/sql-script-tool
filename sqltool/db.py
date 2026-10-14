"""Database access: one persistent pyodbc connection, parameterized queries only."""
import threading

PREFERRED_DRIVERS = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server",
                     "ODBC Driver 13 for SQL Server", "SQL Server Native Client 11.0", "SQL Server")


def available_drivers():
    import pyodbc
    installed = pyodbc.drivers()
    ordered = [d for d in PREFERRED_DRIVERS if d in installed]
    return ordered + [d for d in installed if "SQL Server" in d and d not in ordered]


def _quote(value):
    """Brace-quote an ODBC connection-string value so ; { } in passwords are safe."""
    return "{" + str(value).replace("}", "}}") + "}"


def build_conn_str(info, password, database=None):
    driver = info.driver or (available_drivers() or ["SQL Server"])[0]
    parts = [f"DRIVER={_quote(driver)}", f"SERVER={_quote(info.server)}",
             f"DATABASE={_quote(database or info.database or 'master')}"]
    if info.auth == "windows":
        parts.append("Trusted_Connection=yes")
    else:
        parts += [f"UID={_quote(info.username)}", f"PWD={_quote(password)}"]
    parts.append(f"Encrypt={'yes' if info.encrypt else 'no'}")
    if info.trust_cert:
        parts.append("TrustServerCertificate=yes")
    parts.append("APP=SQL Script Tool")
    return ";".join(parts)


class Database:
    """Thread-safe wrapper. Every call holds a lock, so background jobs never overlap."""

    def __init__(self, info, password, database=None, timeout=15):
        self.info = info
        self.password = password
        self.database = database or info.database or "master"
        self.timeout = timeout
        self._lock = threading.RLock()
        self._conn = None

    # ── connection lifecycle ──────────────────────────────────────
    def connect(self):
        import pyodbc
        with self._lock:
            self.close()
            self._conn = pyodbc.connect(build_conn_str(self.info, self.password, self.database),
                                        timeout=self.timeout, autocommit=False)
            return self

    def close(self):
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def use(self, database):
        """Switch the active database (reconnects)."""
        self.database = database
        return self.connect()

    @property
    def conn(self):
        if self._conn is None:
            self.connect()
        return self._conn

    @property
    def lock(self):
        return self._lock

    # ── queries ───────────────────────────────────────────────────
    def query(self, sql, params=()):
        """Run a read query, returning list of rows. Reconnects once on a dropped link."""
        import pyodbc
        with self._lock:
            for attempt in (1, 2):
                try:
                    cur = self.conn.cursor()
                    cur.execute(sql, params)
                    rows = cur.fetchall() if cur.description else []
                    self._conn.rollback()      # release any shared locks
                    return rows
                except pyodbc.OperationalError:
                    if attempt == 2:
                        raise
                    self.connect()
                except pyodbc.Error as e:
                    # 08S01 = communication link failure
                    if attempt == 1 and e.args and str(e.args[0]).startswith("08"):
                        self.connect()
                        continue
                    raise

    def scalar(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0][0] if rows else None

    def list_databases(self):
        return [r[0] for r in self.query(
            "SELECT name FROM sys.databases WHERE state = 0 ORDER BY name")]
