"""Turso (libSQL) database access over its HTTP API, plus a tiny .env loader.

Settings (in `.env` next to this file, or real environment variables):

    TURSO_DATABASE_URL=libsql://your-db-your-org.turso.io
    TURSO_AUTH_TOKEN=eyJ...

If TURSO_DATABASE_URL is missing, `Database.from_env()` returns None and the
metrics stay in local files (see metrics.py).

No extra packages: statements are sent to Turso's HTTP endpoint
(POST /v2/pipeline) with urllib.
"""

import json
import os
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TIMEOUT = 10


class DatabaseError(Exception):
    pass


# ----------------------------------------------------------------------
# .env
# ----------------------------------------------------------------------
def load_env(path=None):
    """Read KEY=VALUE lines into os.environ. Variables that are already set win,
    so the host's settings (e.g. Render's dashboard) override the file."""
    path = path or os.path.join(HERE, ".env")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return False
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
    return True


# ----------------------------------------------------------------------
# Values <-> Turso's JSON format
# ----------------------------------------------------------------------
def _arg(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return {"type": "text", "value": str(value)}


def _value(cell):
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    return cell.get("value")   # text; blobs come back base64-encoded


def http_url(url):
    """libsql://host -> https://host (Turso's dashboard shows the libsql:// form)."""
    url = url.strip().rstrip("/")
    for prefix, repl in (("libsql://", "https://"), ("wss://", "https://"), ("ws://", "http://")):
        if url.startswith(prefix):
            return repl + url[len(prefix):]
    if "://" not in url:
        return "https://" + url
    return url


# ----------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------
class Database:
    def __init__(self, url, token=None, timeout=TIMEOUT):
        self.url = http_url(url)
        self.token = token
        self.timeout = timeout

    @classmethod
    def from_env(cls):
        load_env()
        url = os.environ.get("TURSO_DATABASE_URL", "").strip()
        if not url:
            return None
        return cls(url, os.environ.get("TURSO_AUTH_TOKEN", "").strip() or None)

    def __repr__(self):
        return f"Database({self.url})"

    def run(self, statements):
        """Run [(sql, args), ...] in one request. Returns one list of row dicts per statement.
        Raises DatabaseError if the request or any statement fails."""
        requests = [{"type": "execute", "stmt": _stmt(sql, args)} for sql, args in statements]
        out = []
        for res in self._post(requests)[:len(statements)]:
            if res.get("type") != "ok":
                raise DatabaseError(_error(res))
            out.append(_rows(res["response"]["result"]))
        if len(out) < len(statements):
            raise DatabaseError("Incomplete answer from the database.")
        return out

    def execute(self, sql, args=()):
        return self.run([(sql, list(args))])[0]

    def transaction(self, statements):
        """Run [(sql, args), ...] all-or-nothing: if one fails, none of them is kept.
        Uses a Hrana batch: each step only runs if the previous one succeeded, and a
        failed COMMIT (or step) ends in ROLLBACK."""
        steps = [{"stmt": _stmt("BEGIN", [])}]
        for sql, args in statements:
            steps.append({"stmt": _stmt(sql, args), "condition": {"type": "ok", "step": len(steps) - 1}})
        commit = len(steps)
        steps.append({"stmt": _stmt("COMMIT", []), "condition": {"type": "ok", "step": commit - 1}})
        steps.append({"stmt": _stmt("ROLLBACK", []),
                      "condition": {"type": "not", "cond": {"type": "ok", "step": commit}}})
        answer = self._post([{"type": "batch", "batch": {"steps": steps}}])
        res = answer[0] if answer else {}
        if res.get("type") != "ok":
            raise DatabaseError(_error(res))
        result = res["response"]["result"]
        errors = [e for e in result.get("step_errors", []) if e]
        if errors:
            raise DatabaseError(errors[0].get("message", "unknown error"))
        done = result.get("step_results", [])
        if len(done) <= commit or done[commit] is None:
            raise DatabaseError("The transaction was not committed.")

    def _post(self, requests):
        body = json.dumps({"requests": requests + [{"type": "close"}]}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.url + "/v2/pipeline", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                answer = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            hint = " (check TURSO_AUTH_TOKEN)" if exc.code in (401, 403) else ""
            raise DatabaseError(f"HTTP {exc.code}{hint}: {detail}") from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise DatabaseError(f"Cannot reach {self.url}: {exc}") from None
        return answer.get("results", [])


def _stmt(sql, args):
    return {"sql": sql, "args": [_arg(a) for a in args]}


def _error(res):
    return (res.get("error") or {}).get("message", "unknown error")


def _rows(result):
    names = [c.get("name") for c in result.get("cols", [])]
    return [{n: _value(c) for n, c in zip(names, row)} for row in result.get("rows", [])]


# Columns added after a table was first created: (table, column, definition, backfill statements).
# `python db.py create` adds the missing ones; the backfill fills them in for matches saved before.
_CAST = ("SELECT x.card_name FROM MatchAction x WHERE x.match_id = MatchAttack.match_id "
         "AND x.action = 'attack' AND x.error IS NULL ORDER BY x.seq {} LIMIT 1")
_NAME = "(SELECT name FROM Attack WHERE id = MatchAttack.attack_id)"
MIGRATIONS = [
    ("MatchAttack", "uses", "INTEGER NOT NULL DEFAULT 0",
     [f"UPDATE MatchAttack SET uses = (SELECT COUNT(*) FROM MatchAction x WHERE x.match_id = MatchAttack.match_id "
      f"AND x.action = 'attack' AND x.error IS NULL AND x.card_name = {_NAME})"]),
    ("MatchAttack", "is_first", "INTEGER NOT NULL DEFAULT 0",
     [f"UPDATE MatchAttack SET is_first = CASE WHEN ({_CAST.format('ASC')}) = {_NAME} THEN 1 ELSE 0 END"]),
    ("MatchAttack", "is_last", "INTEGER NOT NULL DEFAULT 0",
     [f"UPDATE MatchAttack SET is_last = CASE WHEN ({_CAST.format('DESC')}) = {_NAME} THEN 1 ELSE 0 END"]),
]


def migrate(database):
    """Add the columns of MIGRATIONS that are missing (and backfill them). Returns what was added."""
    added = []
    for table, column, definition, backfill in MIGRATIONS:
        try:
            database.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        except DatabaseError as exc:
            if "duplicate column" in str(exc).lower():
                continue
            raise
        if backfill:
            database.run([(sql, []) for sql in backfill])
        added.append(f"{table}.{column}")
    return added


def split_sql(script):
    """Statements of a .sql file (no semicolons inside strings or comments, as in schema.sql)."""
    lines = [line.split("--", 1)[0] for line in script.splitlines()]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] != ["create"]:
        print("Usage: python db.py create [schema.sql]   creates the tables in the database from .env")
        sys.exit(1)
    database = Database.from_env()
    if database is None:
        print("Set TURSO_DATABASE_URL (and TURSO_AUTH_TOKEN) in .env first.")
        sys.exit(1)
    path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "schema.sql")
    with open(path, encoding="utf-8") as f:
        statements = split_sql(f.read())
    try:
        database.run([(s, []) for s in statements])
        added = migrate(database)
    except DatabaseError as exc:
        print("Failed:", exc)
        sys.exit(1)
    print(f"Ran {len(statements)} statement(s) from {os.path.basename(path)} on {database.url}.")
    print("Added columns (and filled them in for older matches): " + ", ".join(added) if added
          else "All columns were already there.")
