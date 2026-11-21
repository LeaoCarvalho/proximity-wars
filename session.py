"""One match plus everything around it: who plays (human or bot), bot moves and
metrics. Used by the server (one per room) and by the offline client."""

from bot import RandomBot
from engine import Match
from metrics import MatchRecorder

BOT_DELAY = 0.8        # seconds a bot waits before acting, so people can follow
BOT_DELAY_FAST = 0.12


class MatchSession:
    def __init__(self, cfg, kinds=("human", "human"), mode="online", room=None, store=None, rng=None):
        self.cfg = cfg
        self.kinds = list(kinds)
        self.match = Match(cfg, rng)
        self.bots = {i: RandomBot() for i, k in enumerate(self.kinds) if k == "bot"}
        self.recorder = MatchRecorder(cfg, self.kinds, mode, room)
        self.store = store
        self.closed = False
        self.record = None

    @property
    def id(self):
        return self.recorder.id

    @property
    def game_over(self):
        return self.match.game_over

    def start(self):
        self.recorder.start()
        return self.match.start()

    def act(self, player, msg):
        if self.closed:
            return [(player, {"type": "error", "message": "The match is over."})]
        card = self._card_name(player, msg)
        outbox = self.match.handle(player, msg)
        self.recorder.action(player, msg, outbox, card=card)
        if self.match.game_over:
            self._close("finished", winner=self.match.winner)
        return outbox

    def _card_name(self, player, msg):
        p = self.match.players[player]
        if msg.get("action") == "attack":
            cards, i = p.hand, msg.get("card")
        elif msg.get("action") == "pick":
            cards, i = p.offer or [], msg.get("index")
        else:
            return None
        if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(cards):
            return cards[i]["name"]
        return None

    def pending_bot(self):
        """Index of a bot that should act now, or None."""
        if self.closed or self.match.game_over:
            return None
        for i in self.bots:
            p = self.match.players[i]
            if p.offer or self.match.turn == i:
                return i
        return None

    def bot_step(self):
        """Let the pending bot take one action. Returns (bot index, outbox) or (None, [])."""
        i = self.pending_bot()
        if i is None:
            return None, []
        msg = self.bots[i].choose(self.match.view(i))
        if msg is None:
            return None, []
        return i, self.act(i, {"type": "action", **msg})

    def spectator_view(self, events=()):
        """What someone watching (bot vs bot) sees: the acting player's view plus both positions."""
        m = self.match
        who = m.winner if m.game_over and m.winner is not None else m.turn
        view = m.view(who)
        view["spectator"] = True
        view["positions"] = [p.pos for p in m.players]
        view["events"] = list(events)
        return view

    def abort(self, disconnected=(), result="disconnected"):
        """A player left (or a bot match was closed) before the end."""
        if not self.closed:
            self._close(result, disconnected=disconnected)

    def _close(self, result, winner=None, disconnected=()):
        self.closed = True
        self.record = self.recorder.finish(result, winner=winner, disconnected=disconnected)
        if self.store is not None:
            self.store.save_match(self.record)

