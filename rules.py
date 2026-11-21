"""Match configuration for Proximity Wars: defaults, presets and validation.

This module is shared by the server and the client and has no third-party
dependencies.

Tiles in configs are numbered 1-10, the same as on the board. Player 1 owns
tiles 1-5 and Player 2 owns tiles 6-10. The engine converts to 0-based.
"""

import copy
import json

BOARD_W = 10
REGION_SIZE = BOARD_W // 2
MAX_DISTANCE = BOARD_W - 1
PLAYER_KEYS = ("p1", "p2")

CURE_MODES = ("A", "B", "C", "custom")
CURE_MODE_NAMES = {
    "A": "A - Recharging points",
    "B": "B - Single-use tiles",
    "C": "C - Roaming point",
    "custom": "Custom",
}
CURE_MODE_ALIASES = {
    "a": "A", "recharging_points": "A",
    "b": "B", "single_use_tiles": "B",
    "c": "C", "roaming_point": "C",
    "custom": "custom",
}
RECHARGE_TYPES = ("each", "all_used")
RESPAWN_TYPES = ("same", "random")

ATTACK_MODES = ("default", "2-2-1", "roguelike")
ATTACK_MODE_NAMES = {
    "default": "Default - fixed loadout",
    "2-2-1": "2-2-1 - shared waiting card",
    "roguelike": "Roguelike - draft new cards",
}

MAX_HAND = 9
MAX_ATTACKS = 60

# Card frame per attack: assets/card_<tier>.png
CARD_TIERS = ("bronze", "silver", "gold")
DEFAULT_TIER = "bronze"

CLASSIC_ATTACKS = [
    {"name": "Magic knife", "damage": 20, "tiles": [1], "desc": "Enchanted knife", "tier": "gold"},
    {"name": "Magical punch", "damage": 10, "tiles": [1, 2], "desc": "Ethereal big conjured hand", "tier": "silver"},
    {"name": "Fireball", "damage": 5, "tiles": [1, 2, 3, 4], "desc": "I said \"I CAST FIREBALL\"", "tier": "bronze"},
    {"name": "Magic bolt", "damage": 4, "tiles": [1, 2, 3, 4, 5], "desc": "A magical ethereal bolt", "tier": "bronze"},
]

SAMPLE_BANK = CLASSIC_ATTACKS + [
    {"name": "Lance", "damage": 14, "tiles": [2], "desc": "Exactly two tiles away", "tier": "gold"},
    {"name": "Long spear", "damage": 12, "tiles": [3], "desc": "Exactly three tiles away", "tier": "silver"},
    {"name": "Whip", "damage": 12, "tiles": [2, 3], "desc": "Cracks at mid range", "tier": "silver"},
    {"name": "Arc bolt", "damage": 8, "tiles": [3, 4, 5], "desc": "Arcs over close targets", "tier": "bronze"},
    {"name": "Meteor", "damage": 10, "tiles": [4, 5, 6], "desc": "Falls far away", "tier": "silver"},
    {"name": "Sniper hex", "damage": 8, "tiles": [6, 7, 8, 9], "desc": "Only hits far targets", "tier": "silver"},
    {"name": "Ricochet", "damage": 11, "tiles": [1, 5, 9], "desc": "Bounces in big steps", "tier": "silver"},
    {"name": "Even storm", "damage": 9, "tiles": [2, 4, 6, 8], "desc": "Only even distances", "tier": "silver"},
    {"name": "Odd storm", "damage": 7, "tiles": [1, 3, 5, 7, 9], "desc": "Only odd distances", "tier": "bronze"},
    {"name": "Ward breaker", "damage": 7, "tiles": [1, 2, 3], "desc": "Short-range burst", "tier": "bronze"},
    {"name": "Shockwave", "damage": 3, "tiles": [1, 2, 3, 4, 5, 6, 7, 8, 9], "desc": "Hits everything", "tier": "bronze"},
]

CURE_DEFAULTS = {
    "A": {"points": {"p1": [1, 5], "p2": [6, 10]}, "value": 8, "cooldown": 3},
    "B": {"values": {"p1": [4, 4, 4, 4, 4], "p2": [4, 4, 4, 4, 4]}},
    "C": {"options": {"p1": [1, 2, 3, 4, 5], "p2": [6, 7, 8, 9, 10]}, "value": 8, "cooldown": 2},
    # The custom defaults reproduce the original game: one cure tile at each
    # edge that jumps to a random tile of your region as soon as it is used.
    "custom": {
        "points": {"p1": [{"tile": 1, "value": 8}], "p2": [{"tile": 10, "value": 8}]},
        "cooldown": 0,
        "recharge": "each",
        "respawn": "random",
        "options": {"p1": [1, 2, 3, 4, 5], "p2": [6, 7, 8, 9, 10]},
    },
}

ATTACK_MODE_DEFAULTS = {
    "default": {},
    "2-2-1": {"hand_size": 2},
    "roguelike": {"initial_cards": 3, "discards_per_pick": 1, "choices": 3},
}

DEFAULT_CONFIG = {
    "max_hp": 30,
    "start": {"p1": "random", "p2": "random"},
    "cure_ends_turn": False,
    "cures_per_turn": 1,
    "cure": dict(mode="custom", **CURE_DEFAULTS["custom"]),
    "attack_mode": {"type": "default"},
    "attacks": CLASSIC_ATTACKS,
}


def default_config():
    return copy.deepcopy(DEFAULT_CONFIG)


def region_tiles(player_index):
    """1-based tile numbers owned by player 0 or 1."""
    start = 1 + player_index * REGION_SIZE
    return list(range(start, start + REGION_SIZE))


def player_label(player_index):
    return f"Player {player_index + 1}"


class ConfigError(Exception):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class _Checker:
    def __init__(self):
        self.errors = []

    def error(self, path, message):
        self.errors.append(f"{path}: {message}")

    def integer(self, value, path, lo=None, hi=None, allow_never=False):
        if allow_never and (value is None or (isinstance(value, str) and value.strip().lower() == "never")):
            return None
        if isinstance(value, bool):
            self.error(path, "must be a number")
            return None
        if isinstance(value, str):
            try:
                value = int(value.strip())
            except ValueError:
                pass
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if not isinstance(value, int):
            hint = ' or "never"' if allow_never else ""
            self.error(path, f"must be a whole number{hint}")
            return None
        if lo is not None and value < lo:
            self.error(path, f"must be at least {lo}")
            return None
        if hi is not None and value > hi:
            self.error(path, f"must be at most {hi}")
            return None
        return value

    def boolean(self, value, path):
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        self.error(path, "must be true or false")
        return False

    def choice(self, value, path, options, aliases=None):
        if isinstance(value, str):
            key = value.strip()
            if aliases:
                key = aliases.get(key.lower(), key)
            if key in options:
                return key
        self.error(path, f"must be one of {', '.join(options)}")
        return None

    def per_player(self, value, path):
        if not isinstance(value, dict):
            self.error(path, 'must be an object like {"p1": ..., "p2": ...}')
            return {"p1": [], "p2": []}
        for key in value:
            if key not in PLAYER_KEYS:
                self.error(f"{path}.{key}", 'unknown key (use "p1" and "p2")')
        return {key: value.get(key, []) for key in PLAYER_KEYS}

    def tile_list(self, value, path, player_index, allow_duplicates=False):
        """A list of 1-based tiles that must all belong to one player's region."""
        if not isinstance(value, list):
            self.error(path, "must be a list of tile numbers")
            return []
        owned = region_tiles(player_index)
        result = []
        for i, raw in enumerate(value):
            tile = self.integer(raw, f"{path}[{i}]", 1, BOARD_W)
            if tile is None:
                continue
            if tile not in owned:
                self.error(
                    path,
                    f"tile {tile} is not in {player_label(player_index)}'s region "
                    f"(tiles {owned[0]}-{owned[-1]})",
                )
                continue
            if tile in result and not allow_duplicates:
                self.error(path, f"tile {tile} is listed twice")
                continue
            result.append(tile)
        return result


def _validate_attack(check, raw, path):
    if not isinstance(raw, dict):
        check.error(path, "must be an object with name, damage and tiles")
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        check.error(f"{path}.name", "must be a non-empty text")
        name = "?"
    damage = check.integer(raw.get("damage"), f"{path}.damage", 0, 999)
    tiles_raw = raw.get("tiles")
    tiles = []
    if not isinstance(tiles_raw, list) or not tiles_raw:
        check.error(f"{path}.tiles", f"must be a non-empty list of distances 1-{MAX_DISTANCE}")
    else:
        for i, t in enumerate(tiles_raw):
            d = check.integer(t, f"{path}.tiles[{i}]", 1, MAX_DISTANCE)
            if d is not None and d not in tiles:
                tiles.append(d)
    desc = raw.get("desc", "")
    if not isinstance(desc, str):
        check.error(f"{path}.desc", "must be text")
        desc = ""
    tier = raw.get("tier", DEFAULT_TIER)
    if tier not in CARD_TIERS:
        check.error(f"{path}.tier", f"must be one of {', '.join(CARD_TIERS)}")
        tier = DEFAULT_TIER
    attack = {"name": name.strip()[:40], "damage": damage or 0, "tiles": sorted(tiles), "desc": desc[:80],
              "tier": tier}
    art = raw.get("art", "")
    if not isinstance(art, str):
        check.error(f"{path}.art", "must be a file name in assets/art")
    elif art.strip():
        attack["art"] = art.strip()[:80]
    return attack


def validate_attacks(raw, path="attacks"):
    """Validate a list of attacks; returns the normalized list or raises ConfigError."""
    check = _Checker()
    attacks = _attacks(check, raw, path)
    if check.errors:
        raise ConfigError(check.errors)
    return attacks


def _attacks(check, raw, path):
    if isinstance(raw, dict) and "attacks" in raw:
        raw = raw["attacks"]
    if not isinstance(raw, list) or not raw:
        check.error(path, "must be a non-empty list of attacks")
        return []
    if len(raw) > MAX_ATTACKS:
        check.error(path, f"at most {MAX_ATTACKS} attacks")
    result = []
    for i, item in enumerate(raw[:MAX_ATTACKS]):
        attack = _validate_attack(check, item, f"{path}[{i}]")
        if attack:
            result.append(attack)
    return result


def _cure(check, raw):
    if not isinstance(raw, dict):
        check.error("cure", "must be an object")
        raw = {}
    mode = check.choice(raw.get("mode", "custom"), "cure.mode", CURE_MODES, CURE_MODE_ALIASES)
    if mode is None:
        return copy.deepcopy(DEFAULT_CONFIG["cure"])
    d = CURE_DEFAULTS[mode]
    get = lambda key: raw.get(key, copy.deepcopy(d.get(key)))  # noqa: E731
    known = set(d) | {"mode"}
    for key in raw:
        if key not in known:
            check.error(f"cure.{key}", f"is not used by cure mode {mode}")

    out = {"mode": mode}
    if mode == "A":
        points = check.per_player(get("points"), "cure.points")
        out["points"] = {k: check.tile_list(points[k], f"cure.points.{k}", i) for i, k in enumerate(PLAYER_KEYS)}
        out["value"] = check.integer(get("value"), "cure.value", 1, 999)
        out["cooldown"] = check.integer(get("cooldown"), "cure.cooldown", 0, 999, allow_never=True)
    elif mode == "B":
        values = check.per_player(get("values"), "cure.values")
        out["values"] = {}
        for i, k in enumerate(PLAYER_KEYS):
            path = f"cure.values.{k}"
            vals = values[k]
            if not isinstance(vals, list) or len(vals) != REGION_SIZE:
                tiles = region_tiles(i)
                check.error(path, f"must list {REGION_SIZE} values, one per tile {tiles[0]}-{tiles[-1]} (0 = no cure)")
                out["values"][k] = [0] * REGION_SIZE
                continue
            out["values"][k] = [check.integer(v, f"{path}[{j}]", 0, 999) or 0 for j, v in enumerate(vals)]
    elif mode == "C":
        options = check.per_player(get("options"), "cure.options")
        out["options"] = {k: check.tile_list(options[k], f"cure.options.{k}", i) for i, k in enumerate(PLAYER_KEYS)}
        out["value"] = check.integer(get("value"), "cure.value", 1, 999)
        out["cooldown"] = check.integer(get("cooldown"), "cure.cooldown", 0, 999)
    else:
        points = check.per_player(get("points"), "cure.points")
        out["points"] = {}
        for i, k in enumerate(PLAYER_KEYS):
            path = f"cure.points.{k}"
            plist = points[k]
            if not isinstance(plist, list):
                check.error(path, 'must be a list of {"tile": n, "value": n}')
                plist = []
            result, seen = [], set()
            for j, p in enumerate(plist):
                if not isinstance(p, dict):
                    check.error(f"{path}[{j}]", 'must be {"tile": n, "value": n}')
                    continue
                tile = check.tile_list([p.get("tile")], f"{path}[{j}].tile", i)
                value = check.integer(p.get("value"), f"{path}[{j}].value", 1, 999)
                if tile and value is not None:
                    if tile[0] in seen:
                        check.error(path, f"tile {tile[0]} is listed twice")
                        continue
                    seen.add(tile[0])
                    result.append({"tile": tile[0], "value": value})
            out["points"][k] = result
        out["cooldown"] = check.integer(get("cooldown"), "cure.cooldown", 0, 999, allow_never=True)
        out["recharge"] = check.choice(get("recharge"), "cure.recharge", RECHARGE_TYPES) or "each"
        out["respawn"] = check.choice(get("respawn"), "cure.respawn", RESPAWN_TYPES) or "same"
        options = check.per_player(get("options"), "cure.options")
        out["options"] = {k: check.tile_list(options[k], f"cure.options.{k}", i) for i, k in enumerate(PLAYER_KEYS)}
        if out["respawn"] == "random":
            for k in PLAYER_KEYS:
                if out["points"][k] and not out["options"][k]:
                    check.error(f"cure.options.{k}", 'needs at least one tile when respawn is "random"')
    return out


def _attack_mode(check, raw, attacks):
    if not isinstance(raw, dict):
        check.error("attack_mode", "must be an object")
        raw = {}
    mode = check.choice(raw.get("type", "default"), "attack_mode.type", ATTACK_MODES)
    if mode is None:
        return {"type": "default"}
    d = ATTACK_MODE_DEFAULTS[mode]
    for key in raw:
        if key not in d and key != "type":
            check.error(f"attack_mode.{key}", f"is not used by attack mode {mode}")
    out = {"type": mode}
    if mode == "default":
        if len(attacks) > MAX_HAND:
            check.error("attacks", f"default mode gives every attack to both players, so use at most {MAX_HAND}")
    elif mode == "2-2-1":
        hand = check.integer(raw.get("hand_size", d["hand_size"]), "attack_mode.hand_size", 1, MAX_HAND)
        out["hand_size"] = hand
        if hand and attacks and len(attacks) < 2 * hand + 1:
            check.error("attacks", f"2-2-1 mode with hand size {hand} needs at least {2 * hand + 1} attacks in the bank")
    else:
        out["initial_cards"] = check.integer(raw.get("initial_cards", d["initial_cards"]), "attack_mode.initial_cards", 1, MAX_HAND)
        out["discards_per_pick"] = check.integer(
            raw.get("discards_per_pick", d["discards_per_pick"]), "attack_mode.discards_per_pick", 1, 99)
        out["choices"] = check.integer(raw.get("choices", d["choices"]), "attack_mode.choices", 1, 5)
    return out


def validate_config(raw):
    """Return a normalized copy of a match config, or raise ConfigError.

    Missing keys fall back to defaults, so partial JSON is accepted.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError([f"Invalid JSON: {exc}"])
    if not isinstance(raw, dict):
        raise ConfigError(["The match config must be a JSON object"])

    check = _Checker()
    known = set(DEFAULT_CONFIG) | {"version"}
    for key in raw:
        if key not in known:
            check.error(key, "unknown setting")

    get = lambda key: raw.get(key, copy.deepcopy(DEFAULT_CONFIG[key]))  # noqa: E731
    cfg = {"version": 1}
    cfg["max_hp"] = check.integer(get("max_hp"), "max_hp", 1, 999)

    start = check.per_player(get("start"), "start")
    cfg["start"] = {}
    for i, k in enumerate(PLAYER_KEYS):
        value = start[k]
        if value in (None, [], "random") or (isinstance(value, str) and value.lower() == "random"):
            cfg["start"][k] = "random"
        else:
            tiles = check.tile_list([value], f"start.{k}", i)
            cfg["start"][k] = tiles[0] if tiles else "random"

    cfg["cure_ends_turn"] = check.boolean(get("cure_ends_turn"), "cure_ends_turn")
    cfg["cures_per_turn"] = check.integer(get("cures_per_turn"), "cures_per_turn", 1, 99)
    cfg["cure"] = _cure(check, get("cure"))
    cfg["attacks"] = _attacks(check, get("attacks"), "attacks")
    cfg["attack_mode"] = _attack_mode(check, get("attack_mode"), cfg["attacks"])

    if check.errors:
        raise ConfigError(check.errors)
    return cfg


def config_to_json(cfg, indent=2):
    return json.dumps(cfg, indent=indent)
