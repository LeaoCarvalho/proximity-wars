"""Match metrics and player feedback.

When TURSO_DATABASE_URL is set (in .env, see db.py), every match goes to the
MatchLog table when it ends (its action log to MatchAction) and feedback to
FeedbackLog; schema.sql has the tables. Without a database, or if it can't be
reached, they are saved as JSON lines in <dir>/matches.jsonl and
<dir>/feedback.jsonl instead. `summary()` turns all of it into the numbers we
track.

Run `python metrics.py [dir]` to print the summary of a metrics folder.
"""

import copy
import hashlib
import json
import os
import sys
import threading
import time
import uuid

from db import Database, DatabaseError
from rules import CLASSIC_ATTACKS, SAMPLE_BANK, validate_attacks

DEFAULT_DIR = os.environ.get("METRICS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data")
FEEDBACK_MAX = 2000
FEEDBACK_TABLE = "FeedbackLog"
FEEDBACK_COLUMNS = ("id", "at", "text", "rating", "match_id", "source")
FROM_ENV = object()
ACTION_KINDS = ("move", "heal", "attack", "pick", "rejected", "total")
ACTION_COLUMNS = ("match_id", "seq", "t", "player", "actor", "action", "direction", "card", "pick_index",
                  "card_name", "p1_hp", "p2_hp", "events", "error")
ACTIONS_PER_INSERT = 50
ATTACK_FIELDS = ("name", "damage", "tiles", "desc", "tier", "art")
DETAILS = ("log", "attack_list")   # the bulky parts of a match record


def attack_id(attack):
    """Fingerprint of an attack definition: the same attack always gets the same id."""
    canonical = {k: attack.get(k) for k in ATTACK_FIELDS}
    canonical["tiles"] = sorted(canonical["tiles"] or [])
    canonical["art"] = canonical["art"] or None
    return hashlib.sha1(_json(canonical).encode("utf-8")).hexdigest()[:16]


def builtin_attack_ids():
    """Fingerprints of the attacks that ship with the game (Classic 4 and the sample bank)."""
    return {attack_id(a) for a in validate_attacks(CLASSIC_ATTACKS + SAMPLE_BANK)}


def attack_from_row(row):
    """An Attack table row -> attack definition (rules.py format)."""
    try:
        tiles = json.loads(row["tiles"])
    except (TypeError, ValueError):
        tiles = []
    attack = {"name": row["name"], "damage": row["damage"], "tiles": tiles,
              "desc": row["description"] or "", "tier": row["tier"]}
    if row.get("art"):
        attack["art"] = row["art"]
    return attack


# ----------------------------------------------------------------------
# Match record <-> database rows (players are 0/1 in records, 1/2 in the database)
# ----------------------------------------------------------------------
def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def match_row(record):
    """The MatchLog row (dict) of a match record."""
    rules = record.get("rules") or {}
    winner = record.get("winner")
    row = {
        "id": record["id"],
        "room": record.get("room"),
        "mode": record["mode"],
        "p1_kind": record["players"][0],
        "p2_kind": record["players"][1],
        "started_at": record.get("started_at"),
        "ended_at": record.get("ended_at"),
        "duration_s": record.get("duration_s"),
        "result": record["result"],
        "winner": winner + 1 if winner is not None else None,
        "winner_kind": record.get("winner_kind"),
        "p1_disconnected": int(0 in record.get("disconnected", ())),
        "p2_disconnected": int(1 in record.get("disconnected", ())),
        "max_hp": rules.get("max_hp"),
        "cure_mode": rules.get("cure_mode"),
        "cure_ends_turn": None if rules.get("cure_ends_turn") is None else int(bool(rules["cure_ends_turn"])),
        "cures_per_turn": rules.get("cures_per_turn"),
        "attack_mode": rules.get("attack_mode"),
        "attacks": _json(rules.get("attacks", [])),
    }
    for i, counts in enumerate(record["actions"]):
        for kind in ACTION_KINDS:
            column = "cures" if kind == "heal" else "picks" if kind == "pick" else \
                "moves" if kind == "move" else "attacks" if kind == "attack" else kind
            row[f"p{i + 1}_{column}"] = counts.get(kind, 0)
    return row


def action_rows(record):
    """The MatchAction rows (tuples in ACTION_COLUMNS order) of a match record."""
    rows = []
    for seq, e in enumerate(record.get("log", []), 1):
        hp = e.get("hp") or [None, None]
        rows.append((record["id"], seq, e.get("t"), e["player"] + 1, e.get("by"), e.get("action"),
                     e.get("direction"), e.get("card"), e.get("index"), e.get("card_name"), hp[0], hp[1],
                     _json(e["events"]) if "events" in e else None, e.get("error")))
    return rows


def record_from_rows(row, actions=None, attack_list=None):
    """Rebuild the match record (same shape as MatchRecorder.finish) from database rows.
    actions: the match's MatchAction rows, attack_list: its attack definitions in order
    (None leaves them out)."""
    counts = []
    for p in ("p1", "p2"):
        c = {"move": row[f"{p}_moves"], "heal": row[f"{p}_cures"], "attack": row[f"{p}_attacks"],
             "pick": row[f"{p}_picks"], "rejected": row[f"{p}_rejected"], "total": row[f"{p}_total"]}
        counts.append(c)
    try:
        attacks = json.loads(row["attacks"]) if row.get("attacks") else []
    except ValueError:
        attacks = []
    record = {
        "id": row["id"],
        "room": row["room"],
        "mode": row["mode"],
        "players": [row["p1_kind"], row["p2_kind"]],
        "rules": {
            "max_hp": row["max_hp"],
            "cure_mode": row["cure_mode"],
            "cure_ends_turn": None if row["cure_ends_turn"] is None else bool(row["cure_ends_turn"]),
            "cures_per_turn": row["cures_per_turn"],
            "attack_mode": row["attack_mode"],
            "attacks": attacks,
        },
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "duration_s": row["duration_s"],
        "result": row["result"],
        "winner": row["winner"] - 1 if row["winner"] is not None else None,
        "winner_kind": row["winner_kind"],
        "disconnected": [i for i, p in enumerate(("p1", "p2")) if row[f"{p}_disconnected"]],
        "actions": counts,
        "cures_used": [c["heal"] for c in counts],
    }
    if actions is not None:
        log = []
        for a in actions:
            e = {"t": a["t"], "player": a["player"] - 1, "by": a["actor"], "action": a["action"]}
            for key, column in (("direction", "direction"), ("card", "card"), ("index", "pick_index"),
                                ("card_name", "card_name"), ("error", "error")):
                if a[column] is not None:
                    e[key] = a[column]
            if a["events"] is not None:
                try:
                    e["events"] = json.loads(a["events"])
                except ValueError:
                    e["events"] = []
            if a["p1_hp"] is not None or a["p2_hp"] is not None:
                e["hp"] = [a["p1_hp"], a["p2_hp"]]
            log.append(e)
        record["log"] = log
    if attack_list is not None:
        record["attack_list"] = attack_list
    return record


def now_iso(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t if t is not None else time.time()))


# ----------------------------------------------------------------------
# One match
# ----------------------------------------------------------------------
class MatchRecorder:
    """Collects everything about one match while it is played."""

    def __init__(self, cfg, kinds, mode, room=None):
        self.id = uuid.uuid4().hex[:12]
        self.kinds = list(kinds)
        self.mode = mode
        self.room = room
        self.rules = {
            "max_hp": cfg["max_hp"],
            "cure_mode": cfg["cure"]["mode"],
            "cure_ends_turn": cfg["cure_ends_turn"],
            "cures_per_turn": cfg["cures_per_turn"],
            "attack_mode": cfg["attack_mode"]["type"],
            "attacks": [a["name"] for a in cfg["attacks"]],
        }
        self.attack_list = copy.deepcopy(cfg["attacks"])   # full definitions of the attacks in play
        self.started = None
        self.log = []
        self.actions = [{"move": 0, "heal": 0, "attack": 0, "pick": 0, "rejected": 0} for _ in range(2)]

    def start(self):
        self.started = time.time()

    def elapsed(self):
        return round(time.time() - self.started, 2) if self.started else 0.0

    def action(self, player, msg, outbox, card=None):
        """Record an action and the engine's answer (outbox of (player, message))."""
        kind = msg.get("action")
        error = next((m.get("message") for p, m in outbox if p == player and m.get("type") == "error"), None)
        entry = {"t": self.elapsed(), "player": player, "by": self.kinds[player], "action": kind}
        for key in ("direction", "card", "index"):
            if key in msg:
                entry[key] = msg[key]
        if card:
            entry["card_name"] = card
        state = next((m for p, m in outbox if p == player and m.get("type") == "state"), None)
        if error:
            entry["error"] = error
            self.actions[player]["rejected"] += 1
        else:
            if kind in self.actions[player]:
                self.actions[player][kind] += 1
            if state:
                entry["events"] = state.get("events", [])
                entry["hp"] = [state["your_hp"], state["opponent_hp"]] if player == 0 else \
                    [state["opponent_hp"], state["your_hp"]]
        self.log.append(entry)

    def finish(self, result, winner=None, disconnected=()):
        """result: "finished", "disconnected" (a player left mid-match) or "stopped" (bot match closed)."""
        ended = time.time()
        totals = []
        for a in self.actions:
            t = dict(a)
            t["total"] = a["move"] + a["heal"] + a["attack"] + a["pick"]
            totals.append(t)
        return {
            "id": self.id,
            "room": self.room,
            "mode": self.mode,
            "players": self.kinds,
            "rules": self.rules,
            "started_at": now_iso(self.started),
            "ended_at": now_iso(ended),
            "duration_s": round(ended - self.started, 2) if self.started else 0.0,
            "result": result,
            "winner": winner,
            "winner_kind": self.kinds[winner] if winner is not None else None,
            "disconnected": sorted(disconnected),
            "actions": totals,
            "cures_used": [a["heal"] for a in self.actions],
            "log": self.log,
            "attack_list": self.attack_list,
        }


# ----------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------
class MetricsStore:
    def __init__(self, directory=None, db=FROM_ENV):
        """db: a db.Database, None for files only, or (default) the one configured in .env."""
        self.dir = directory or DEFAULT_DIR
        self.db = Database.from_env() if db is FROM_ENV else db
        self.lock = threading.Lock()
        self._saving = []   # background threads writing matches to the database

    def _path(self, name):
        return os.path.join(self.dir, name)

    def _append(self, name, record):
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self.lock:
            os.makedirs(self.dir, exist_ok=True)
            with open(self._path(name), "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def _read(self, name):
        try:
            with open(self._path(name), encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return out

    def save_match(self, record):
        """Save a finished match. With a database this happens in a background thread
        (the server's game loop must not wait for the network); flush() waits for it."""
        if self.db is None:
            self._save_match_file(record)
            return
        thread = threading.Thread(target=self._save_match_db, args=(record,), name="save-match")
        with self.lock:
            self._saving = [t for t in self._saving if t.is_alive()] + [thread]
        thread.start()

    def flush(self, timeout=None):
        """Wait until the matches being saved in the background are written."""
        for thread in list(self._saving):
            thread.join(timeout)

    def _save_match_file(self, record):
        try:
            self._append("matches.jsonl", record)
        except OSError as exc:
            print("Could not save match metrics:", exc, file=sys.stderr)

    def _save_match_db(self, record):
        try:
            row = match_row(record)
            statements = [("DELETE FROM MatchAction WHERE match_id = ?", [record["id"]]),
                          ("DELETE FROM MatchAttack WHERE match_id = ?", [record["id"]]),
                          (f"INSERT OR REPLACE INTO MatchLog ({', '.join(row)}) "
                           f"VALUES ({', '.join('?' * len(row))})", list(row.values()))]
            for slot, attack in enumerate(record.get("attack_list") or [], 1):
                aid = attack_id(attack)
                statements.append((
                    "INSERT OR IGNORE INTO Attack (id, name, damage, tiles, description, tier, art, first_seen_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [aid, attack["name"], attack["damage"], _json(sorted(attack["tiles"])), attack.get("desc", ""),
                     attack.get("tier"), attack.get("art") or None, record.get("ended_at")]))
                statements.append(("INSERT INTO MatchAttack (match_id, slot, attack_id) VALUES (?, ?, ?)",
                                   [record["id"], slot, aid]))
            actions = action_rows(record)
            one = "(" + ", ".join("?" * len(ACTION_COLUMNS)) + ")"
            for i in range(0, len(actions), ACTIONS_PER_INSERT):
                chunk = actions[i:i + ACTIONS_PER_INSERT]
                statements.append((f"INSERT INTO MatchAction ({', '.join(ACTION_COLUMNS)}) VALUES "
                                   + ", ".join([one] * len(chunk)), [v for r in chunk for v in r]))
            self.db.transaction(statements)   # all or nothing
        except (DatabaseError, KeyError, TypeError, IndexError) as exc:
            print("Could not save the match in the database, keeping it in a file:", exc, file=sys.stderr)
            self._save_match_file(record)

    def save_feedback(self, entry):
        """entry: {"text", "rating" (1-5 or None), "match_id", "source"}; returns the stored record."""
        text = str(entry.get("text", "")).strip()[:FEEDBACK_MAX]
        rating = entry.get("rating")
        if not (isinstance(rating, int) and not isinstance(rating, bool) and 1 <= rating <= 5):
            rating = None
        record = {
            "id": uuid.uuid4().hex[:12],
            "at": now_iso(),
            "text": text,
            "rating": rating,
            "match_id": str(entry.get("match_id") or "")[:16] or None,
            "source": str(entry.get("source") or "")[:32] or None,
        }
        if self.db is not None:
            try:
                self.db.execute(
                    f"INSERT INTO {FEEDBACK_TABLE} ({', '.join(FEEDBACK_COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?)",
                    [record[c] for c in FEEDBACK_COLUMNS])
                return record
            except DatabaseError as exc:
                print("Could not save feedback in the database, keeping it in a file:", exc, file=sys.stderr)
        self._append("feedback.jsonl", record)
        return record

    def matches(self, limit=None, log=True):
        """Oldest first, the latest `limit` ones. log=False leaves the action logs out."""
        if self.db is not None:
            try:
                return self._matches_db(limit, log)
            except DatabaseError as exc:
                print("Could not read matches from the database, using the local file:", exc, file=sys.stderr)
        records = self._read("matches.jsonl")
        records = records[-limit:] if limit else records
        if not log:
            records = [{k: v for k, v in r.items() if k not in DETAILS} for r in records]
        return records

    def _matches_db(self, limit, log):
        sql = "SELECT * FROM MatchLog ORDER BY ended_at DESC, rowid DESC"
        rows = self.db.execute(sql + " LIMIT ?", [int(limit)]) if limit else self.db.execute(sql)
        rows.reverse()
        if not log or not rows:
            return [record_from_rows(r) for r in rows]
        by_match = {r["id"]: [] for r in rows}
        attacks = {r["id"]: [] for r in rows}
        cols = ", ".join(ACTION_COLUMNS)
        attack_sql = ("SELECT m.match_id, a.* FROM MatchAttack m JOIN Attack a ON a.id = m.attack_id"
                      "{} ORDER BY m.match_id, m.slot")
        if limit:
            where = f" WHERE match_id IN ({', '.join('?' * len(by_match))})"
            actions, used = self.db.run([
                (f"SELECT {cols} FROM MatchAction{where} ORDER BY match_id, seq", list(by_match)),
                (attack_sql.format(where.replace("match_id", "m.match_id")), list(by_match))])
        else:
            actions, used = self.db.run([(f"SELECT {cols} FROM MatchAction ORDER BY match_id, seq", []),
                                         (attack_sql.format(""), [])])
        for a in actions:
            if a["match_id"] in by_match:
                by_match[a["match_id"]].append(a)
        for a in used:
            if a["match_id"] in attacks:
                attacks[a["match_id"]].append(attack_from_row(a))
        return [record_from_rows(r, by_match[r["id"]], attacks[r["id"]]) for r in rows]

    def stored_attack_ids(self, ids):
        """Which of these attack fingerprints are stored (database, or the local match file
        without one). Raises DatabaseError if the database can't be reached."""
        ids = list(dict.fromkeys(ids))
        if not ids:
            return set()
        if self.db is not None:
            rows = self.db.execute(f"SELECT id FROM Attack WHERE id IN ({', '.join('?' * len(ids))})", ids)
            return {r["id"] for r in rows}
        wanted = set(ids)
        known = {attack_id(a) for r in self._read("matches.jsonl") for a in r.get("attack_list") or []}
        known |= {attack_id(e["attack"]) for e in self._read("attacks.jsonl") if isinstance(e.get("attack"), dict)}
        return known & wanted

    def save_attacks(self, attacks):
        """Store attack definitions (already validated) without a match, e.g. from the dev
        attack editor. Returns (added, already_stored). Raises DatabaseError / OSError."""
        unique = {}
        for a in attacks:
            unique.setdefault(attack_id(a), a)
        stored = self.stored_attack_ids(list(unique))
        new = {aid: a for aid, a in unique.items() if aid not in stored}
        if new and self.db is not None:
            self.db.transaction([
                ("INSERT OR IGNORE INTO Attack (id, name, damage, tiles, description, tier, art, first_seen_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 [aid, a["name"], a["damage"], _json(sorted(a["tiles"])), a.get("desc", ""), a.get("tier"),
                  a.get("art") or None, now_iso()]) for aid, a in new.items()])
        elif new:
            for a in new.values():
                self._append("attacks.jsonl", {"at": now_iso(), "attack": a})
        return len(new), len(unique) - len(new)

    def attacks(self, limit=300):
        """Every different attack that was played or saved, most recently used (or saved) first:
        [{"id", "attack": {...definition...}, "matches": n, "last_used": time, "saved_at": time}, ...]."""
        if self.db is not None:
            try:
                rows = self.db.execute(
                    "SELECT a.*, COUNT(m.match_id) AS matches, MAX(l.ended_at) AS last_used FROM Attack a "
                    "LEFT JOIN MatchAttack m ON m.attack_id = a.id LEFT JOIN MatchLog l ON l.id = m.match_id "
                    "GROUP BY a.id ORDER BY COALESCE(MAX(l.ended_at), a.first_seen_at) DESC, a.name LIMIT ?",
                    [int(limit)])
                return [{"id": r["id"], "attack": attack_from_row(r), "matches": r["matches"],
                         "last_used": r["last_used"], "saved_at": r["first_seen_at"]} for r in rows]
            except DatabaseError as exc:
                print("Could not read attacks from the database, using the local file:", exc, file=sys.stderr)
        found = {}
        for e in self._read("attacks.jsonl"):
            if isinstance(e.get("attack"), dict):
                aid = attack_id(e["attack"])
                found.setdefault(aid, {"id": aid, "attack": e["attack"], "matches": 0, "last_used": None,
                                       "saved_at": e.get("at")})
        for record in self._read("matches.jsonl"):
            for attack in record.get("attack_list") or []:
                aid = attack_id(attack)
                entry = found.setdefault(aid, {"id": aid, "attack": attack, "matches": 0, "last_used": None,
                                               "saved_at": record.get("ended_at")})
                entry["matches"] += 1
                entry["last_used"] = max(entry["last_used"] or "", record.get("ended_at") or "") or None
        ordered = sorted(found.values(), key=lambda e: e["attack"]["name"])
        ordered.sort(key=lambda e: e["last_used"] or e["saved_at"] or "", reverse=True)
        return ordered[:limit]

    def feedback(self, limit=None):
        """Oldest first. From the database when there is one (the local file is only a fallback)."""
        if self.db is not None:
            try:
                sql = f"SELECT {', '.join(FEEDBACK_COLUMNS)} FROM {FEEDBACK_TABLE} ORDER BY at DESC, rowid DESC"
                rows = self.db.execute(sql + " LIMIT ?", [int(limit)]) if limit else self.db.execute(sql)
                return rows[::-1]
            except DatabaseError as exc:
                print("Could not read feedback from the database, using the local file:", exc, file=sys.stderr)
        records = self._read("feedback.jsonl")
        return records[-limit:] if limit else records

    def summary(self):
        return summarize(self.matches(log=False), self.feedback())


def _avg(values):
    values = list(values)
    return round(sum(values) / len(values), 2) if values else None


def summarize(matches, feedback=()):
    finished = [m for m in matches if m["result"] == "finished"]
    disconnected = [m for m in matches if m["result"] == "disconnected"]
    vs_bot = [m for m in finished if sorted(m["players"]) == ["bot", "human"]]
    bot_vs_bot = [m for m in finished if m["players"] == ["bot", "bot"]]

    cures_all = sum(sum(m["cures_used"]) for m in matches)
    cures_winner = sum(m["cures_used"][m["winner"]] for m in finished if m["winner"] is not None)
    cures_loser = sum(m["cures_used"][1 - m["winner"]] for m in finished if m["winner"] is not None)

    def actions(ms):
        return [a["total"] for m in ms for a in m["actions"]]

    ratings = [f["rating"] for f in feedback if f.get("rating")]
    return {
        "matches": {
            "total": len(matches),
            "finished": len(finished),
            "with_disconnect": len(disconnected),
            "one_player_disconnected": sum(1 for m in disconnected if len(m["disconnected"]) == 1),
            "both_players_disconnected": sum(1 for m in disconnected if len(m["disconnected"]) >= 2),
            "bot_matches_stopped": sum(1 for m in matches if m["result"] == "stopped"),
            "online": sum(1 for m in matches if m["mode"] == "online"),
            "offline": sum(1 for m in matches if m["mode"] == "offline"),
        },
        "duration_s": {
            "average_finished": _avg(m["duration_s"] for m in finished),
            "longest_finished": max((m["duration_s"] for m in finished), default=None),
            "shortest_finished": min((m["duration_s"] for m in finished), default=None),
        },
        "actions_per_player": {
            "average_finished": _avg(actions(finished)),
            "average_all": _avg(actions(matches)),
        },
        "bot": {
            "vs_human_finished": len(vs_bot),
            "bot_won_vs_human": sum(1 for m in vs_bot if m["winner_kind"] == "bot"),
            "human_won_vs_bot": sum(1 for m in vs_bot if m["winner_kind"] == "human"),
            "bot_vs_bot_finished": len(bot_vs_bot),
            "bot_wins_total": sum(1 for m in finished if m["winner_kind"] == "bot"),
        },
        "cures_used": {
            "total": cures_all,
            "by_winners": cures_winner,
            "by_losers": cures_loser,
            "average_per_match": _avg(sum(m["cures_used"]) for m in matches),
        },
        "feedback": {
            "count": len(feedback),
            "average_rating": _avg(ratings),
        },
    }


if __name__ == "__main__":
    if sys.argv[1:2] == ["save-builtin-attacks"]:
        store = MetricsStore()
        added, already = store.save_attacks(validate_attacks(CLASSIC_ATTACKS + SAMPLE_BANK))
        print(f"Built-in attacks in {store.db or os.path.abspath(store.dir)}: {added} added, {already} already there.")
        sys.exit(0)
    store = MetricsStore(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"Metrics in {store.db}" if store.db else f"Metrics in {os.path.abspath(store.dir)}")
    print(json.dumps(store.summary(), indent=2))
