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
        requests = [{"type": "execute", "stmt": {"sql": sql, "args": [_arg(a) for a in args]}}
                    for sql, args in statements]
        requests.append({"type": "close"})
        body = json.dumps({"requests": requests}).encode("utf-8")
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

        out = []
        for res in answer.get("results", [])[:len(statements)]:
            if res.get("type") != "ok":
                raise DatabaseError((res.get("error") or {}).get("message", "unknown error"))
            result = res["response"]["result"]
            names = [c.get("name") for c in result.get("cols", [])]
            out.append([{n: _value(c) for n, c in zip(names, row)} for row in result.get("rows", [])])
        if len(out) < len(statements):
            raise DatabaseError("Incomplete answer from the database.")
        return out

    def execute(self, sql, args=()):
        return self.run([(sql, list(args))])[0]
