"""Offline transport: runs the match on this computer instead of on a server.

It has the same interface as NetPeer (send / poll / running / close), so the
game screen does not care where the match lives.

- Two humans (hot seat): actions are made as the player being viewed, and the
  view follows whoever's turn it is. `switch()` changes player by hand.
- Human vs bot: you are Player 1; the bot plays Player 2.
- Bot vs bot: you watch.

Finished and abandoned matches are saved to the local metrics folder (data/).
"""

import time

from metrics import MetricsStore
from rules import default_config, validate_config
from session import BOT_DELAY, BOT_DELAY_FAST, MatchSession


class LocalPeer:
    def __init__(self, cfg=None, players=("human", "human"), store=None, bot_delay=BOT_DELAY):
        self.cfg = validate_config(cfg) if cfg else default_config()
        self.session = MatchSession(self.cfg, players, mode="offline",
                                    store=store if store is not None else MetricsStore())
        self.match = self.session.match
        self.humans = [i for i, k in enumerate(players) if k == "human"]
        self.spectator = not self.humans
        self.hot_seat = len(self.humans) == 2
        self.viewer = self.humans[0] if self.humans else 0
        self.bot_delay = bot_delay
        self.fast = False
        self.next_bot_at = None
        self.running = True
        self.inbox = [{"type": "match_start", "player": self.viewer, "config": self.cfg, "offline": True,
                       "spectator": self.spectator, "players": list(players), "match_id": self.session.id}]
        self._deliver(self.session.start(), actor=None)

    # ------------------------------------------------------------------
    def _deliver(self, outbox, actor):
        if self.spectator:
            if any(m.get("type") == "state" for _, m in outbox):
                events = next((m.get("events", []) for p, m in outbox
                               if m.get("type") == "state" and (actor is None or p == actor)), [])
                if actor is not None:
                    events = [f"Bot {actor + 1}: {e}" for e in events]
                self.inbox.append(self.session.spectator_view(events))
            return
        for player, msg in outbox:
            if player == self.viewer:
                self.inbox.append(msg)

    def send(self, message):
        kind = message.get("type")
        if kind == "speed":
            self.fast = bool(message.get("fast"))
            return
        if kind != "action" or not self.running or self.spectator:
            return
        actor = self.viewer
        outbox = self.session.act(actor, message)
        self._deliver(outbox, actor)
        m = self.match
        if self.hot_seat and not m.game_over and m.turn != actor and any(p == actor for p, _ in outbox):
            self.switch(m.turn)

    def switch(self, player=None):
        """Hot seat only: view (and act as) `player`; with no argument, the other player."""
        if not self.hot_seat:
            return
        self.viewer = 1 - self.viewer if player is None else player
        state = self.match.view(self.viewer)
        state["events"] = [f"Now playing as Player {self.viewer + 1}."]
        self.inbox.append(state)

    def opponent_pos(self):
        return self.match.players[1 - self.viewer].pos

    def _run_bots(self):
        if self.session.pending_bot() is None:
            self.next_bot_at = None
            return
        now = time.monotonic()
        if self.next_bot_at is None:
            self.next_bot_at = now + (BOT_DELAY_FAST if self.fast else self.bot_delay)
        elif now >= self.next_bot_at:
            self.next_bot_at = None
            actor, outbox = self.session.bot_step()
            self._deliver(outbox, actor)

    def poll(self):
        if self.running:
            self._run_bots()
        messages, self.inbox = self.inbox, []
        return messages

    def close(self):
        """Leaving before the end counts as a disconnect (or a stopped bot match)."""
        if self.running and not self.session.closed:
            if self.spectator:
                self.session.abort(result="stopped")
            else:
                self.session.abort(disconnected=[self.viewer])
        self.running = False
