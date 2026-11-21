"""The simplest possible bot: every time it acts, it picks a random legal action.

It only looks at the same view a human client gets (never the opponent's
position), so it can run on the server or on the client.
"""

import random

from rules import REGION_SIZE


def legal_actions(view):
    """Every action the player in `view` may take right now, as engine messages."""
    if view["game_over"]:
        return []
    actions = []
    offer = view.get("offer") or []
    # a pending card choice is the only thing a player can do off-turn
    actions += [{"action": "pick", "index": i} for i in range(len(offer))]
    if not view["your_turn"]:
        return actions

    pos = view["your_pos"]
    lo = 0 if view["player"] == 0 else REGION_SIZE
    for d in (-1, 1):
        if lo <= pos + d < lo + REGION_SIZE:
            actions.append({"action": "move", "direction": d})
    if view["cures_left_this_turn"] > 0 and any(c["active"] and c["tile"] == pos for c in view["cures"]):
        actions.append({"action": "heal"})
    actions += [{"action": "attack", "card": i} for i in range(len(view["hand"]))]
    return actions


class RandomBot:
    name = "random"

    def __init__(self, rng=None):
        self.rng = rng or random.Random()

    def choose(self, view):
        """A random legal action (as an engine message), or None if it cannot act."""
        actions = legal_actions(view)
        if not actions:
            return None
        return self.rng.choice(actions)
