"""Offline transport: runs the match engine in-process instead of on a server.

It has the same interface as NetPeer (send / poll / running / close), so the
game screen does not care where the engine lives. Both players share one
screen (hot seat): actions are made as the player being viewed, and the view
follows whoever's turn it is. `switch()` changes the viewed player by hand.
"""

import random

from engine import Match
from rules import default_config, validate_config


class LocalPeer:
    def __init__(self, cfg=None, seed=None, follow_turn=True):
        self.cfg = validate_config(cfg) if cfg else default_config()
        self.match = Match(self.cfg, random.Random(seed))
        self.running = True
        self.follow_turn = follow_turn
        self.viewer = 0
        self.inbox = [{"type": "match_start", "player": 0, "config": self.cfg, "offline": True}]
        for player, message in self.match.start():
            if player == self.viewer:
                self.inbox.append(message)

    def send(self, message):
        if message.get("type") != "action" or not self.running:
            return
        actor = self.viewer
        outbox = self.match.handle(actor, message)
        for player, msg in outbox:
            if player == actor:
                self.inbox.append(msg)
        m = self.match
        if self.follow_turn and not m.game_over and m.turn != actor and any(p == actor for p, _ in outbox):
            self.switch(m.turn)

    def switch(self, player=None):
        """View (and act as) `player`; with no argument, the other player."""
        self.viewer = 1 - self.viewer if player is None else player
        state = self.match.view(self.viewer)
        state["events"] = [f"Now playing as Player {self.viewer + 1}."]
        self.inbox.append(state)

    def opponent_pos(self):
        return self.match.players[1 - self.viewer].pos

    def poll(self):
        messages, self.inbox = self.inbox, []
        return messages

    def close(self):
        self.running = False
