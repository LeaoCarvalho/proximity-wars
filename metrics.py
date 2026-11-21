"""Match metrics and player feedback.

Every match is saved as one JSON line in <dir>/matches.jsonl when it ends, and
every feedback message as one line in <dir>/feedback.jsonl. `summary()` turns
those files into the numbers we track.

Run `python metrics.py [dir]` to print the summary of a metrics folder.
"""

import json
import os
import sys
import threading
import time
import uuid

DEFAULT_DIR = os.environ.get("METRICS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data")
FEEDBACK_MAX = 2000


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
        }


# ----------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------
class MetricsStore:
    def __init__(self, directory=None):
        self.dir = directory or DEFAULT_DIR
        self.lock = threading.Lock()

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
        try:
            self._append("matches.jsonl", record)
        except OSError as exc:
            print("Could not save match metrics:", exc, file=sys.stderr)

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
            "match_id": str(entry.get("match_id") or "")[:40] or None,
            "source": str(entry.get("source") or "")[:40] or None,
        }
        self._append("feedback.jsonl", record)
        return record

    def matches(self, limit=None):
        records = self._read("matches.jsonl")
        return records[-limit:] if limit else records

    def feedback(self, limit=None):
        records = self._read("feedback.jsonl")
        return records[-limit:] if limit else records

    def summary(self):
        return summarize(self.matches(), self.feedback())


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
    store = MetricsStore(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"Metrics in {os.path.abspath(store.dir)}")
    print(json.dumps(store.summary(), indent=2))
