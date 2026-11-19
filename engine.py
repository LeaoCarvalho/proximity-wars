"""Authoritative match rules for Proximity Wars.

`Match` knows nothing about networking. `start()` and `handle()` return an
outbox: a list of (player_index, message) pairs for the server to send.
Every successful action sends each player a full "state" snapshot of what
that player is allowed to see, plus a list of event lines for the log.
"""

import copy
import random
from dataclasses import dataclass, field

from rules import BOARD_W, PLAYER_KEYS, REGION_SIZE, region_tiles


@dataclass
class CurePoint:
    tile: int          # 0-based
    value: int
    active: bool = True
    timer: int | None = None   # own turns until it is back; None = not counting


@dataclass
class CureSet:
    points: list
    cooldown: int | None       # None = never recharges
    recharge: str              # "each" or "all_used"
    respawn: str               # "same" or "random"
    options: list              # 0-based tiles a point can respawn on
    group_timer: int | None = None   # used by "all_used"


@dataclass
class Player:
    pos: int
    hp: int
    cures: CureSet
    hand: list = field(default_factory=list)
    cures_this_turn: int = 0
    discards: int = 0          # roguelike: discards since the last offer
    pending_offers: int = 0    # roguelike: offers earned but not yet shown
    offer: list | None = None  # roguelike: cards to choose from right now


def build_cures(cfg, player_index, rng):
    """Translate any cure mode into the general CureSet model."""
    c = cfg["cure"]
    key = PLAYER_KEYS[player_index]
    mode = c["mode"]
    if mode == "A":
        points = [CurePoint(t - 1, c["value"]) for t in c["points"][key]]
        return CureSet(points, c["cooldown"], "all_used", "same", [])
    if mode == "B":
        first = player_index * REGION_SIZE
        points = [CurePoint(first + i, v) for i, v in enumerate(c["values"][key]) if v > 0]
        return CureSet(points, None, "each", "same", [])
    if mode == "C":
        options = [t - 1 for t in c["options"][key]]
        points = [CurePoint(rng.choice(options), c["value"])] if options else []
        return CureSet(points, c["cooldown"], "each", "random", options)
    points = [CurePoint(p["tile"] - 1, p["value"]) for p in c["points"][key]]
    options = [t - 1 for t in c["options"][key]]
    return CureSet(points, c["cooldown"], c["recharge"], c["respawn"], options)


class Match:
    def __init__(self, cfg, rng=None):
        self.cfg = cfg
        self.rng = rng or random.Random()
        self.max_hp = cfg["max_hp"]
        self.mode = cfg["attack_mode"]
        self.bank = cfg["attacks"]
        self.turn = 0
        self.game_over = False
        self.winner = None
        self.wait_card = None

        self.players = []
        for i, key in enumerate(PLAYER_KEYS):
            start = cfg["start"][key]
            if start == "random":
                pos = self.rng.choice([t - 1 for t in region_tiles(i)])
            else:
                pos = start - 1
            self.players.append(Player(pos=pos, hp=self.max_hp, cures=build_cures(cfg, i, self.rng)))

        self._deal()

    # ------------------------------------------------------------------
    # Cards
    # ------------------------------------------------------------------
    def _card(self, card):
        return copy.deepcopy(card)

    def _deal(self):
        kind = self.mode["type"]
        if kind == "default":
            for p in self.players:
                p.hand = [self._card(c) for c in self.bank]
        elif kind == "2-2-1":
            h = self.mode["hand_size"]
            drawn = [self._card(c) for c in self.rng.sample(self.bank, 2 * h + 1)]
            self.players[0].hand = drawn[:h]
            self.players[1].hand = drawn[h:2 * h]
            self.wait_card = drawn[2 * h]
        else:
            for p in self.players:
                p.hand = [self._card(self.rng.choice(self.bank)) for _ in range(self.mode["initial_cards"])]

    def _make_offer(self, p):
        k = self.mode["choices"]
        if len(self.bank) >= k:
            cards = self.rng.sample(self.bank, k)
        else:
            cards = [self.rng.choice(self.bank) for _ in range(k)]
        p.offer = [self._card(c) for c in cards]
        p.pending_offers -= 1

    # ------------------------------------------------------------------
    # Cures
    # ------------------------------------------------------------------
    def _reactivate(self, cs, point):
        point.active = True
        point.timer = None
        if cs.respawn == "random" and cs.options:
            taken = {q.tile for q in cs.points if q.active and q is not point}
            free = [t for t in cs.options if t not in taken] or cs.options
            point.tile = self.rng.choice(free)

    def _use_cure(self, cs, point):
        point.active = False
        if cs.recharge == "each":
            if cs.cooldown is None:
                return
            if cs.cooldown == 0:
                self._reactivate(cs, point)
            else:
                point.timer = cs.cooldown
        else:
            if any(q.active for q in cs.points) or cs.cooldown is None:
                return
            if cs.cooldown == 0:
                for q in cs.points:
                    self._reactivate(cs, q)
            else:
                cs.group_timer = cs.cooldown

    def _tick_cures(self, cs):
        """Called at the start of the owner's turn."""
        if cs.recharge == "each":
            for q in cs.points:
                if not q.active and q.timer is not None:
                    q.timer -= 1
                    if q.timer <= 0:
                        self._reactivate(cs, q)
        elif cs.group_timer is not None:
            cs.group_timer -= 1
            if cs.group_timer <= 0:
                cs.group_timer = None
                for q in cs.points:
                    self._reactivate(cs, q)

    # ------------------------------------------------------------------
    # Turn flow
    # ------------------------------------------------------------------
    def _begin_turn(self, index):
        p = self.players[index]
        p.cures_this_turn = 0
        self._tick_cures(p.cures)

    def _end_turn(self):
        self.turn = 1 - self.turn
        self._begin_turn(self.turn)

    def start(self):
        self._begin_turn(self.turn)
        return self._states(["Match started. Player 1 moves first."], ["Match started. Player 1 moves first."])

    def handle(self, player, msg):
        if self.game_over:
            return self._error(player, "The match is over.")
        action = msg.get("action")
        if action == "pick":
            return self._pick(player, msg)
        if player != self.turn:
            return self._error(player, "It is not your turn.")
        if action == "move":
            return self._move(player, msg)
        if action == "heal":
            return self._heal(player)
        if action == "attack":
            return self._attack(player, msg)
        return self._error(player, "Unknown action.")

    def _move(self, player, msg):
        direction = msg.get("direction")
        if direction not in (-1, 1):
            return self._error(player, "Invalid move.")
        p = self.players[player]
        new_pos = p.pos + direction
        if new_pos + 1 not in region_tiles(player):
            return self._error(player, "You cannot leave your region.")
        p.pos = new_pos
        self._end_turn()
        return self._states_for(player, [f"You moved to tile {new_pos + 1}."], ["Opponent moved."])

    def _heal(self, player):
        p = self.players[player]
        if p.cures_this_turn >= self.cfg["cures_per_turn"]:
            limit = self.cfg["cures_per_turn"]
            return self._error(player, f"You can only cure {limit} time(s) per turn.")
        point = next((q for q in p.cures.points if q.active and q.tile == p.pos), None)
        if point is None:
            return self._error(player, "There is no active cure on your tile.")
        gained = min(self.max_hp, p.hp + point.value) - p.hp
        p.hp += gained
        p.cures_this_turn += 1
        self._use_cure(p.cures, point)
        mine = [f"You cured +{gained} HP."]
        theirs = [f"Opponent cured +{gained} HP."]
        if self.cfg["cure_ends_turn"]:
            self._end_turn()
        return self._states_for(player, mine, theirs)

    def _attack(self, player, msg):
        p = self.players[player]
        if not p.hand:
            if p.offer is not None:
                return self._error(player, "Pick a new card first.")
            return self._error(player, "You have no cards left.")
        card_index = msg.get("card")
        if not isinstance(card_index, int) or isinstance(card_index, bool) or not 0 <= card_index < len(p.hand):
            return self._error(player, "Invalid card.")

        card = p.hand[card_index]
        other = 1 - player
        enemy = self.players[other]
        distance = abs(p.pos - enemy.pos)
        hit = distance in card["tiles"]
        damage = card["damage"] if hit else 0
        enemy.hp = max(0, enemy.hp - damage)

        kind = self.mode["type"]
        extra = []
        if kind == "2-2-1":
            p.hand[card_index], self.wait_card = self.wait_card, card
            extra.append(f"You drew {p.hand[card_index]['name']}.")
        elif kind == "roguelike":
            p.hand.pop(card_index)
            p.discards += 1
            while p.discards >= self.mode["discards_per_pick"]:
                p.discards -= self.mode["discards_per_pick"]
                p.pending_offers += 1
            if p.offer is None and p.pending_offers > 0:
                self._make_offer(p)
                extra.append("Choose a new card.")

        name = card["name"]
        if hit:
            mine = [f"{name}: HIT for {damage} damage."]
            theirs = [f"Opponent's {name} hit you for {damage} damage."]
        else:
            mine = [f"{name}: MISS."]
            theirs = [f"Opponent's {name} missed."]

        if enemy.hp <= 0:
            self.game_over = True
            self.winner = player
            mine.append("You win!")
            theirs.append("You lose.")
        else:
            self._end_turn()
        return self._states_for(player, mine + extra, theirs)

    def _pick(self, player, msg):
        p = self.players[player]
        if p.offer is None:
            return self._error(player, "There is no card to pick.")
        index = msg.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(p.offer):
            return self._error(player, "Invalid choice.")
        card = p.offer[index]
        p.hand.append(card)
        p.offer = None
        events = [f"You picked {card['name']}."]
        if p.pending_offers > 0:
            self._make_offer(p)
            events.append("Choose another card.")
        return self._states_for(player, events, [])

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------
    def view(self, index):
        p = self.players[index]
        enemy = self.players[1 - index]
        cs = p.cures
        view = {
            "type": "state",
            "player": index,
            "turn": self.turn,
            "your_turn": self.turn == index and not self.game_over,
            "your_pos": p.pos,
            "your_hp": p.hp,
            "opponent_hp": enemy.hp,
            "max_hp": self.max_hp,
            "hand": copy.deepcopy(p.hand),
            "opponent_hand_size": len(enemy.hand),
            "attack_mode": self.mode["type"],
            "cures": [
                {"tile": q.tile, "value": q.value, "active": q.active, "timer": q.timer}
                for q in cs.points
            ],
            "cure_respawn": cs.respawn,
            "cure_recharge": cs.recharge,
            "cure_group_timer": cs.group_timer,
            "cures_left_this_turn": self.cfg["cures_per_turn"] - p.cures_this_turn,
            "cure_ends_turn": self.cfg["cure_ends_turn"],
            "game_over": self.game_over,
            "winner": self.winner,
        }
        if self.mode["type"] == "2-2-1":
            view["wait_card"] = copy.deepcopy(self.wait_card)
        if self.mode["type"] == "roguelike":
            view["offer"] = copy.deepcopy(p.offer)
            view["offers_pending"] = p.pending_offers
            view["discards_until_pick"] = self.mode["discards_per_pick"] - p.discards
        return view

    def _states(self, events0, events1):
        out = []
        for i, events in enumerate((events0, events1)):
            state = self.view(i)
            state["events"] = events
            out.append((i, state))
        return out

    def _states_for(self, actor, mine, theirs):
        if actor == 0:
            return self._states(mine, theirs)
        return self._states(theirs, mine)

    def _error(self, player, message):
        return [(player, {"type": "error", "message": message})]


__all__ = ["Match", "BOARD_W"]
