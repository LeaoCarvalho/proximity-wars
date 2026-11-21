"""Match setup form and custom attack editor."""

import copy
import json
import os

import pygame

import rules
from rules import (
    ATTACK_MODE_DEFAULTS, ATTACK_MODE_NAMES, ATTACK_MODES, CURE_DEFAULTS, CURE_MODE_NAMES,
    CARD_TIERS, CURE_MODES, ConfigError, DEFAULT_TIER, MAX_DISTANCE, config_to_json, validate_attacks, validate_config,
)
from ui import (
    ACCENT, BAD, BG, BORDER, Button, Cycle, DIM, GOOD, HEIGHT, MUTED, PANEL, PANEL_HI, TEXT,
    TextField, TilePicker, TileValues, Toggle, WARN, WIDTH, copy_to_clipboard, fit_text, font,
    paste_from_clipboard, region_color, text,
)

TILES = list(range(1, 11))


def _num(s):
    s = str(s).strip()
    try:
        return int(s)
    except ValueError:
        return s


def _cooldown(s):
    s = str(s).strip()
    if s == "" or s.lower() == "never":
        return None
    return _num(s)


def _show_cooldown(v):
    return "never" if v is None else str(v)


class Messages:
    """Status line / error list shown at the bottom of a screen."""

    def __init__(self):
        self.lines = []
        self.color = MUTED

    def info(self, s):
        self.lines, self.color = [s], GOOD

    def errors(self, errs, title="Fix these settings first:"):
        self.lines, self.color = [title] + list(errs), BAD

    def draw(self, surface, x, y, max_lines=3, width=WIDTH - 60):
        shown = self.lines[:max_lines]
        if len(self.lines) > max_lines:
            shown[-1] = f"... and {len(self.lines) - max_lines + 1} more problem(s)"
        for i, line in enumerate(shown):
            text(surface, fit_text(line, 16, width), (x, y + i * 19), 16, self.color if i == 0 else WARN)


class SetupScreen:
    TOP, BOTTOM = 70, 588
    LABEL_X, WIDGET_X = 40, 330

    def __init__(self, app, cfg=None):
        self.app = app
        self.msg = Messages()
        self.scroll = 0
        colors = region_color

        start_opts = lambda tiles: [("random", "Random")] + [(t, f"Tile {t}") for t in tiles]  # noqa: E731
        self.max_hp = TextField(w=100)
        self.cure_ends_turn = Toggle()
        self.cures_per_turn = TextField(w=100)
        self.start_p1 = Cycle(start_opts(range(1, 6)), w=160)
        self.start_p2 = Cycle(start_opts(range(6, 11)), w=160)

        self.cure_mode = Cycle([(m, CURE_MODE_NAMES[m]) for m in CURE_MODES], w=330)
        self.a_points = TilePicker(TILES, colors=colors)
        self.a_value = TextField(w=100)
        self.a_cooldown = TextField(w=100, placeholder="never")
        self.b_values = TileValues(TILES, colors=colors)
        self.c_options = TilePicker(TILES, colors=colors)
        self.c_value = TextField(w=100)
        self.c_cooldown = TextField(w=100)
        self.x_points = TileValues(TILES, colors=colors)
        self.x_cooldown = TextField(w=100, placeholder="never")
        self.x_recharge = Cycle([("each", "Each point on its own"),
                                 ("all_used", "All together, after all are used")], w=330)
        self.x_respawn = Cycle([("same", "On the same tile"), ("random", "On a random option tile")], w=330)
        self.x_options = TilePicker(TILES, colors=colors)

        self.attack_mode = Cycle([(m, ATTACK_MODE_NAMES[m]) for m in ATTACK_MODES], w=330)
        self.hand_size = TextField(w=100)
        self.initial_cards = TextField(w=100)
        self.discards_per_pick = TextField(w=100)
        self.choices = TextField(w=100)
        self.attacks = []
        self.opponent = Cycle([("pvp", "Another player"), ("bot", "The bot (random moves)"),
                               ("bot_vs_bot", "Bot vs bot (watch)")], w=330)
        self.where = Cycle([("online", "Online server"), ("offline", "This computer (no server)")], w=330)
        self.visibility = Cycle([("private", "Private (code only)"), ("public", "Public (anyone can join)")],
                                w=330)
        self.btn_edit = Button("Edit attacks...", lambda: app.set_screen(AttackEditor(app, self)))
        self.btn_classic = Button("Classic 4", self._use_classic)
        self.btn_sample = Button("Sample bank (15)", self._use_sample)

        self.path = TextField("match.json", w=150, placeholder="file.json")
        self.bottom_buttons = [
            Button("Back", app.show_menu),
            Button("Copy JSON", self.copy_json),
            Button("Paste > form", lambda: self.paste_json(start=False)),
            Button("Paste > start", lambda: self.paste_json(start=True)),
            self.path,
            Button("Load", self.load_file),
            Button("Save", self.save_file),
            Button("START MATCH", self.start, primary=True),
        ]

        self._load_mode_defaults()
        self.load(cfg or rules.default_config())

    # ------------------------------------------------------------------
    # Config <-> form
    # ------------------------------------------------------------------
    def _load_mode_defaults(self):
        for mode in CURE_MODES:
            self._load_cure(dict(mode=mode, **copy.deepcopy(CURE_DEFAULTS[mode])))
        for mode in ATTACK_MODES:
            self._load_attack_mode(dict(type=mode, **ATTACK_MODE_DEFAULTS[mode]))

    def _load_cure(self, c):
        mode = c["mode"]
        if mode == "A":
            self.a_points.selected = set(c["points"]["p1"] + c["points"]["p2"])
            self.a_value.value = str(c["value"])
            self.a_cooldown.value = _show_cooldown(c["cooldown"])
        elif mode == "B":
            vals = c["values"]["p1"] + c["values"]["p2"]
            self.b_values.set_values({t: v for t, v in zip(TILES, vals)})
        elif mode == "C":
            self.c_options.selected = set(c["options"]["p1"] + c["options"]["p2"])
            self.c_value.value = str(c["value"])
            self.c_cooldown.value = str(c["cooldown"])
        else:
            pts = c["points"]["p1"] + c["points"]["p2"]
            self.x_points.set_values({p["tile"]: p["value"] for p in pts})
            self.x_cooldown.value = _show_cooldown(c["cooldown"])
            self.x_recharge.set(c["recharge"])
            self.x_respawn.set(c["respawn"])
            self.x_options.selected = set(c["options"]["p1"] + c["options"]["p2"])
        self.cure_mode.set(mode)

    def _load_attack_mode(self, a):
        mode = a["type"]
        if mode == "2-2-1":
            self.hand_size.value = str(a["hand_size"])
        elif mode == "roguelike":
            self.initial_cards.value = str(a["initial_cards"])
            self.discards_per_pick.value = str(a["discards_per_pick"])
            self.choices.value = str(a["choices"])
        self.attack_mode.set(mode)

    def load(self, cfg):
        """Fill the form from a normalized config."""
        self.max_hp.value = str(cfg["max_hp"])
        self.cure_ends_turn.value = cfg["cure_ends_turn"]
        self.cures_per_turn.value = str(cfg["cures_per_turn"])
        self.start_p1.set(cfg["start"]["p1"])
        self.start_p2.set(cfg["start"]["p2"])
        self._load_cure(cfg["cure"])
        self._load_attack_mode(cfg["attack_mode"])
        self.attacks = copy.deepcopy(cfg["attacks"])

    def raw_config(self):
        def split(tiles):
            return {"p1": sorted(t for t in tiles if t <= 5), "p2": sorted(t for t in tiles if t > 5)}

        mode = self.cure_mode.value
        if mode == "A":
            cure = {"mode": "A", "points": split(self.a_points.selected),
                    "value": _num(self.a_value.value), "cooldown": _cooldown(self.a_cooldown.value)}
        elif mode == "B":
            vals = self.b_values.values()
            row = [(_num(vals[t]) if vals[t] else 0) for t in TILES]
            cure = {"mode": "B", "values": {"p1": row[:5], "p2": row[5:]}}
        elif mode == "C":
            cure = {"mode": "C", "options": split(self.c_options.selected),
                    "value": _num(self.c_value.value), "cooldown": _num(self.c_cooldown.value)}
        else:
            vals = self.x_points.values()
            pts = [{"tile": t, "value": _num(vals[t])} for t in TILES if vals[t] not in ("", "0")]
            cure = {
                "mode": "custom",
                "points": {"p1": [p for p in pts if p["tile"] <= 5], "p2": [p for p in pts if p["tile"] > 5]},
                "cooldown": _cooldown(self.x_cooldown.value),
                "recharge": self.x_recharge.value,
                "respawn": self.x_respawn.value,
                "options": split(self.x_options.selected),
            }

        amode = {"type": self.attack_mode.value}
        if amode["type"] == "2-2-1":
            amode["hand_size"] = _num(self.hand_size.value)
        elif amode["type"] == "roguelike":
            amode["initial_cards"] = _num(self.initial_cards.value)
            amode["discards_per_pick"] = _num(self.discards_per_pick.value)
            amode["choices"] = _num(self.choices.value)

        return {
            "max_hp": _num(self.max_hp.value),
            "start": {"p1": self.start_p1.value, "p2": self.start_p2.value},
            "cure_ends_turn": self.cure_ends_turn.value,
            "cures_per_turn": _num(self.cures_per_turn.value),
            "cure": cure,
            "attack_mode": amode,
            "attacks": copy.deepcopy(self.attacks),
        }

    def config(self):
        """Normalized config, or None after showing the errors."""
        try:
            return validate_config(self.raw_config())
        except ConfigError as exc:
            self.msg.errors(exc.errors)
            return None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _use_classic(self):
        self.attacks = copy.deepcopy(rules.CLASSIC_ATTACKS)
        self.msg.info("Loaded the 4 classic attacks.")

    def _use_sample(self):
        self.attacks = copy.deepcopy(rules.SAMPLE_BANK)
        self.msg.info("Loaded the 15-card sample bank.")

    def start(self):
        cfg = self.config()
        if not cfg:
            return
        mode, offline = self.opponent.value, self.where.value == "offline"
        if mode == "pvp" and not offline:
            self.app.start_match(cfg, private=self.visibility.value == "private")
        else:
            self.app.launch(mode, offline=offline, cfg=cfg)

    def copy_json(self):
        cfg = self.config()
        if cfg:
            ok = copy_to_clipboard(config_to_json(cfg))
            self.msg.info("Match JSON copied to the clipboard." if ok else "Could not access the clipboard.")

    def apply_json(self, raw, start, source):
        try:
            cfg = validate_config(raw)
        except ConfigError as exc:
            self.msg.errors(exc.errors, f"The JSON from {source} has problems:")
            return
        self.load(cfg)
        if start:
            self.start()  # uses the Opponent / Play on / Visibility choices
        else:
            self.msg.info(f"Loaded settings from {source}.")

    def paste_json(self, start):
        raw = paste_from_clipboard().strip()
        if not raw:
            self.msg.errors(["The clipboard is empty."], "Nothing to paste:")
            return
        self.apply_json(raw, start, "the clipboard")

    def load_file(self):
        path = self.path.value.strip()
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
        except OSError as exc:
            self.msg.errors([str(exc)], "Could not read the file:")
            return
        self.apply_json(raw, False, os.path.basename(path))

    def save_file(self):
        cfg = self.config()
        if not cfg:
            return
        path = self.path.value.strip()
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(config_to_json(cfg))
        except OSError as exc:
            self.msg.errors([str(exc)], "Could not save the file:")
            return
        self.msg.info(f"Saved to {os.path.abspath(path)}")

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def rows(self):
        R = []
        H = lambda s: R.append(("header", s))  # noqa: E731
        row = lambda label, widgets, hint="": R.append(("row", label, widgets, hint))  # noqa: E731
        note = lambda s, color=MUTED: R.append(("note", s, color))  # noqa: E731

        H("Match")
        row("Opponent", [self.opponent], "click / right-click to change")
        row("Play on", [self.where])
        if self.opponent.value == "pvp" and self.where.value == "online":
            row("Visibility", [self.visibility])
            if self.visibility.value == "private":
                note("Only players who type your match code can join.")
            else:
                note("Your code works, and anyone who clicks Join match with an empty code box may also join.")
        elif self.opponent.value == "pvp":
            note("Both players share this screen (hot seat).")
        H("General")
        row("Max HP (starting health)", [self.max_hp])
        row("Start tile", [self.start_p1, self.start_p2], "Player 1 / Player 2")
        row("Curing ends your turn", [self.cure_ends_turn])
        row("Cures allowed per turn", [self.cures_per_turn])

        H("Cure system")
        row("Cure mode", [self.cure_mode], "click / right-click to change")
        mode = self.cure_mode.value
        if mode == "A":
            note("Fixed cure points. Once a player has used all of theirs, they recharge together after the cooldown.")
            row("Cure points", [self.a_points], "tiles 1-5 are P1's, 6-10 are P2's")
            row("Cure value", [self.a_value], "HP per cure")
            row("Recharge cooldown", [self.a_cooldown], "your turns; 0 = instant, never")
        elif mode == "B":
            note("Every tile holds one cure that never comes back. Leave a box empty for no cure there.")
            row("Cure value per tile", [self.b_values])
        elif mode == "C":
            note("One cure point per player. When used it is destroyed and, after the cooldown,")
            note("a new one appears on a random tile from that player's options.")
            row("Possible cure tiles", [self.c_options], "tiles 1-5 are P1's, 6-10 are P2's")
            row("Cure value", [self.c_value], "HP per cure")
            row("Respawn cooldown", [self.c_cooldown], "your turns; 0 = instant")
        else:
            note("Mix the pieces: any number of points, any cooldown, and how/where they come back.")
            row("Cure points (HP value)", [self.x_points], "empty = no point")
            row("Cooldown", [self.x_cooldown], "your turns; 0 = instant, never")
            row("Recharge", [self.x_recharge])
            row("Comes back", [self.x_respawn])
            if self.x_respawn.value == "random":
                row("Respawn option tiles", [self.x_options])

        H("Attacks")
        row("Card mode", [self.attack_mode], "click / right-click to change")
        amode = self.attack_mode.value
        if amode == "default":
            note("Both players always have every attack in the list below.")
        elif amode == "2-2-1":
            note("Cards are drawn from the bank: one hand per player and 1 waiting card. Using a card")
            note("swaps it with the waiting card, which the other player may then draw.")
            row("Cards per hand", [self.hand_size], "2 = the 2-2-1 rule")
        else:
            note("Start with random cards. Every few used cards you choose a new one from random options.")
            row("Starting cards", [self.initial_cards])
            row("Used cards per new pick", [self.discards_per_pick])
            row("Options to choose from", [self.choices])
        row("Attack list / bank", [self.btn_edit, self.btn_classic, self.btn_sample])
        names = ", ".join(a["name"] for a in self.attacks) or "(empty)"
        note(fit_text(f"{len(self.attacks)} attack(s): {names}", 16, WIDTH - 100), TEXT)
        return R

    def layout(self):
        """Place visible widgets; returns [(kind, data, y, height)]."""
        placed = []
        y = self.TOP + 8 - self.scroll
        self.visible = []
        for item in self.rows():
            kind = item[0]
            if kind == "header":
                h = 44
            elif kind == "note":
                h = 22
            else:
                widgets = item[2]
                h = max(w.rect.h for w in widgets) + 12
                x = self.WIDGET_X
                for w in widgets:
                    w.place(x, y + 4)
                    x += w.rect.w + 10
                    if self.TOP <= w.rect.y and w.rect.bottom <= self.BOTTOM:
                        self.visible.append(w)
            placed.append((item, y, h))
            y += h
        self.content_h = y + self.scroll - self.TOP + 10

        x = 30
        for b in self.bottom_buttons:
            b.place(x, HEIGHT - 52)
            x += b.rect.w + 8
        return placed

    def widgets(self):
        return self.visible + self.bottom_buttons

    def handle(self, event):
        self.layout()
        if event.type == pygame.MOUSEWHEEL:
            max_scroll = max(0, self.content_h - (self.BOTTOM - self.TOP))
            self.scroll = min(max_scroll, max(0, self.scroll - event.y * 40))
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            TextField.blur()
        if event.type == pygame.MOUSEBUTTONDOWN and event.pos[1] > self.BOTTOM:
            candidates = self.bottom_buttons
        else:
            candidates = self.widgets()
        for w in candidates:
            if w.handle(event):
                return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.show_menu()

    def update(self):
        pass

    def draw(self, surface):
        placed = self.layout()
        surface.fill(BG)
        text(surface, "MATCH SETUP", (WIDTH // 2, 18), 34, bold=True, center=True)

        surface.set_clip(pygame.Rect(0, self.TOP, WIDTH, self.BOTTOM - self.TOP))
        for item, y, h in placed:
            if y + h < self.TOP or y > self.BOTTOM:
                continue
            kind = item[0]
            if kind == "header":
                text(surface, item[1].upper(), (self.LABEL_X, y + 14), 20, ACCENT, bold=True)
                pygame.draw.line(surface, BORDER, (self.LABEL_X, y + 40), (WIDTH - 40, y + 40))
            elif kind == "note":
                text(surface, item[1], (self.LABEL_X + 10, y + 2), 16, item[2])
            else:
                _, label, widgets, hint = item
                text(surface, label, (self.LABEL_X, y + 11), 18)
                for w in widgets:
                    w.draw(surface)
                if hint:
                    hx = widgets[-1].rect.right + 14
                    text(surface, fit_text(hint, 15, WIDTH - hx - 20), (hx, y + 13), 15, DIM)
        surface.set_clip(None)

        if self.content_h > self.BOTTOM - self.TOP:
            track = pygame.Rect(WIDTH - 14, self.TOP, 6, self.BOTTOM - self.TOP)
            pygame.draw.rect(surface, PANEL, track, border_radius=3)
            frac = (self.BOTTOM - self.TOP) / self.content_h
            th = max(30, int(track.h * frac))
            max_scroll = self.content_h - (self.BOTTOM - self.TOP)
            ty = track.y + int((track.h - th) * (self.scroll / max_scroll if max_scroll else 0))
            pygame.draw.rect(surface, BORDER, (track.x, ty, track.w, th), border_radius=3)

        pygame.draw.line(surface, BORDER, (0, self.BOTTOM + 2), (WIDTH, self.BOTTOM + 2))
        self.msg.draw(surface, 30, self.BOTTOM + 8)
        for b in self.bottom_buttons:
            b.draw(surface)


# ----------------------------------------------------------------------
# Attack editor
# ----------------------------------------------------------------------
class AttackEditor:
    LIST_X, LIST_Y, LIST_W, ROW_H = 30, 80, 380, 30
    LIST_ROWS = 14

    def __init__(self, app, setup):
        self.app = app
        self.setup = setup
        self.msg = Messages()
        self.items = [self._item(a) for a in setup.attacks] or [self._item(None)]
        self.scroll = 0
        self.selected = -1

        fx = 470
        self.name = TextField(w=300, max_len=40).place(fx + 130, 90)
        self.damage = TextField(w=100, max_len=4).place(fx + 130, 136)
        self.tier = Cycle([(t, t.capitalize()) for t in CARD_TIERS], w=150).place(fx + 300, 136)
        self.desc = TextField(w=300, max_len=80).place(fx + 130, 182)
        self.tiles = TilePicker(range(1, MAX_DISTANCE + 1), box=48).place(fx + 130, 250)
        quick = [("All", lambda d: True), ("None", lambda d: False),
                 ("Even", lambda d: d % 2 == 0), ("Odd", lambda d: d % 2 == 1),
                 ("Near 1-3", lambda d: d <= 3), ("Far 6-9", lambda d: d >= 6)]
        self.quick = []
        x = fx + 130
        for label, pred in quick:
            b = Button(label, lambda p=pred: self._quick(p), h=30, size=16).place(x, 306)
            self.quick.append(b)
            x += b.rect.w + 6

        y = self.LIST_Y + self.LIST_ROWS * self.ROW_H + 12
        self.list_buttons = []
        x = self.LIST_X
        for label, fn in [("New", self.new), ("Duplicate", self.duplicate), ("Delete", self.delete),
                          ("Up", lambda: self.move(-1)), ("Down", lambda: self.move(1))]:
            b = Button(label, fn, h=32, size=16).place(x, y)
            self.list_buttons.append(b)
            x += b.rect.w + 6

        self.path = TextField("attacks.json", w=200, placeholder="file.json")
        self.bottom = [
            Button("Cancel", self.cancel),
            Button("Copy JSON", self.copy_json),
            Button("Paste JSON", self.paste_json),
            self.path,
            Button("Load file", self.load_file),
            Button("Save file", self.save_file),
            Button("Done", self.done, primary=True),
        ]
        x = 30
        for b in self.bottom:
            b.place(x, HEIGHT - 52)
            x += b.rect.w + 8
        self._select(0)

    @staticmethod
    def _item(a):
        if a is None:
            return {"name": "New attack", "damage": "5", "tiles": {1}, "desc": "", "tier": DEFAULT_TIER, "art": ""}
        return {"name": a["name"], "damage": str(a["damage"]), "tiles": set(a["tiles"]), "desc": a.get("desc", ""),
                "tier": a.get("tier", DEFAULT_TIER), "art": a.get("art", "")}

    def _select(self, i):
        self._store()
        self.selected = max(0, min(i, len(self.items) - 1))
        item = self.items[self.selected]
        self.name.value = item["name"]
        self.damage.value = item["damage"]
        self.desc.value = item["desc"]
        self.tier.set(item["tier"])
        self.tiles.selected = item["tiles"]  # shared set: edits apply directly
        if self.selected < self.scroll:
            self.scroll = self.selected
        elif self.selected >= self.scroll + self.LIST_ROWS:
            self.scroll = self.selected - self.LIST_ROWS + 1

    def _store(self):
        if not getattr(self, "items", None) or not 0 <= getattr(self, "selected", -1) < len(self.items):
            return
        item = self.items[self.selected]
        item["name"] = self.name.value
        item["damage"] = self.damage.value
        item["desc"] = self.desc.value
        item["tier"] = self.tier.value
        item["tiles"] = self.tiles.selected

    def _quick(self, pred):
        self.tiles.selected.clear()
        self.tiles.selected.update(d for d in range(1, MAX_DISTANCE + 1) if pred(d))

    def attacks_raw(self):
        self._store()
        out = []
        for it in self.items:
            a = {"name": it["name"], "damage": _num(it["damage"]), "tiles": sorted(it["tiles"]),
                 "desc": it["desc"], "tier": it["tier"]}
            if it["art"]:
                a["art"] = it["art"]
            out.append(a)
        return out

    def attacks(self):
        try:
            return validate_attacks(self.attacks_raw())
        except ConfigError as exc:
            self.msg.errors(exc.errors)
            return None

    def set_attacks(self, attacks, source):
        self.items = [self._item(a) for a in attacks]
        self.selected = -1
        self._select(0)
        self.msg.info(f"Loaded {len(attacks)} attack(s) from {source}.")

    # actions -----------------------------------------------------------
    def new(self):
        self._store()
        self.items.append(self._item(None))
        self._select(len(self.items) - 1)

    def duplicate(self):
        self._store()
        it = self.items[self.selected]
        copy_item = {**it, "tiles": set(it["tiles"]), "name": (it["name"] + " copy")[:40]}
        self.items.insert(self.selected + 1, copy_item)
        self._select(self.selected + 1)

    def delete(self):
        if len(self.items) <= 1:
            self.msg.errors(["Keep at least one attack."], "Cannot delete:")
            return
        self.items.pop(self.selected)
        i = min(self.selected, len(self.items) - 1)
        self.selected = -1
        self._select(i)

    def move(self, step):
        self._store()
        j = self.selected + step
        if 0 <= j < len(self.items):
            self.items[self.selected], self.items[j] = self.items[j], self.items[self.selected]
            self.selected = -1
            self._select(j)

    def copy_json(self):
        attacks = self.attacks()
        if attacks:
            ok = copy_to_clipboard(json.dumps({"attacks": attacks}, indent=2))
            self.msg.info("Attacks JSON copied." if ok else "Could not access the clipboard.")

    def _parse(self, raw, source):
        try:
            attacks = validate_attacks(json.loads(raw))
        except json.JSONDecodeError as exc:
            self.msg.errors([str(exc)], f"Invalid JSON in {source}:")
            return
        except ConfigError as exc:
            self.msg.errors(exc.errors, f"The attacks in {source} have problems:")
            return
        self.set_attacks(attacks, source)

    def paste_json(self):
        self._parse(paste_from_clipboard(), "the clipboard")

    def load_file(self):
        path = self.path.value.strip()
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
        except OSError as exc:
            self.msg.errors([str(exc)], "Could not read the file:")
            return
        self._parse(raw, os.path.basename(path))

    def save_file(self):
        attacks = self.attacks()
        if not attacks:
            return
        path = self.path.value.strip()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"attacks": attacks}, f, indent=2)
        except OSError as exc:
            self.msg.errors([str(exc)], "Could not save the file:")
            return
        self.msg.info(f"Saved {len(attacks)} attack(s) to {os.path.abspath(path)}")

    def done(self):
        attacks = self.attacks()
        if attacks:
            self.setup.attacks = attacks
            self.setup.msg.info(f"Attack list updated ({len(attacks)} attacks).")
            self.app.set_screen(self.setup)

    def cancel(self):
        self.app.set_screen(self.setup)

    # events / drawing ------------------------------------------------------
    def row_rect(self, visible_index):
        return pygame.Rect(self.LIST_X, self.LIST_Y + visible_index * self.ROW_H, self.LIST_W, self.ROW_H - 2)

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            TextField.blur()
            for vi in range(self.LIST_ROWS):
                i = self.scroll + vi
                if i < len(self.items) and self.row_rect(vi).collidepoint(event.pos):
                    self._select(i)
                    return
        if event.type == pygame.MOUSEWHEEL:
            max_scroll = max(0, len(self.items) - self.LIST_ROWS)
            self.scroll = min(max_scroll, max(0, self.scroll - event.y))
            return
        for w in [self.name, self.damage, self.tier, self.desc, self.tiles, *self.quick, *self.list_buttons,
                  *self.bottom]:
            if w.handle(event):
                self._store()
                return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.cancel()

    def update(self):
        pass

    def _draw_card_preview(self, surface, rect):
        """The selected attack as it looks in a match (only when it is valid)."""
        try:
            card = validate_attacks(self.attacks_raw()[self.selected: self.selected + 1])[0]
        except (ConfigError, IndexError):
            return
        from game import scaled_card
        surface.blit(scaled_card(card, rect.w), rect)

    def draw(self, surface):
        self._store()
        surface.fill(BG)
        text(surface, "ATTACK EDITOR", (WIDTH // 2, 18), 34, bold=True, center=True)
        text(surface, f"Attacks ({len(self.items)})", (self.LIST_X, self.LIST_Y - 24), 17, MUTED)

        for vi in range(self.LIST_ROWS):
            i = self.scroll + vi
            if i >= len(self.items):
                break
            it = self.items[i]
            r = self.row_rect(vi)
            sel = i == self.selected
            pygame.draw.rect(surface, PANEL_HI if sel else PANEL, r, border_radius=5)
            if sel:
                pygame.draw.rect(surface, ACCENT, r, 1, border_radius=5)
            text(surface, fit_text(it["name"] or "(no name)", 17, 190), (r.x + 8, r.y + 5), 17)
            text(surface, f"{it['damage']} dmg", (r.x + 205, r.y + 5), 16, MUTED)
            tiles = ",".join(str(t) for t in sorted(it["tiles"])) or "-"
            text(surface, fit_text(tiles, 15, 110), (r.right - 8, r.y + 6), 15, DIM, right=True)
        if len(self.items) > self.LIST_ROWS:
            text(surface, "scroll for more", (self.LIST_X + self.LIST_W, self.LIST_Y - 22), 14, DIM, right=True)
        for b in self.list_buttons:
            b.draw(surface)

        fx = 470
        text(surface, "Name", (fx, 97), 18)
        text(surface, "Damage", (fx, 143), 18)
        text(surface, "Tier", (fx + 250, 143), 18)
        text(surface, "Description", (fx, 189), 18)
        text(surface, "Hit distances", (fx, 236), 18)
        text(surface, "tiles away from the caster", (fx, 258), 14, DIM)
        for w in [self.name, self.damage, self.tier, self.desc, self.tiles, *self.quick]:
            w.draw(surface)
        self._draw_card_preview(surface, pygame.Rect(fx + 452, 86, 160, 110))

        # Preview: Player 1 on tile 3 casting toward the right.
        text(surface, "Preview (Player 1 on tile 3 casting at Player 2's side):", (fx, 360), 16, MUTED)
        caster = 3
        size, gap = 54, 4
        for t in range(1, 11):
            r = pygame.Rect(fx + (t - 1) * (size + gap), 386, size, size)
            base = (38, 65, 92) if t <= 5 else (78, 50, 72)
            hit = (t - caster) in self.tiles.selected
            pygame.draw.rect(surface, (200, 80, 80) if hit else base, r, border_radius=6)
            text(surface, t, (r.x + 4, r.y + 2), 13, MUTED)
            if t == caster:
                pygame.draw.circle(surface, TEXT, r.center, 16)
                text(surface, "1", (r.centerx, r.centery - 11), 20, BG, bold=True, center=True)
        text(surface, "Red tiles are hit. Player 2 casts the same distances toward the left.", (fx, 448), 14, DIM)

        it = self.items[self.selected]
        dmg = _num(it["damage"])
        self.damage.invalid = not isinstance(dmg, int) or dmg < 0
        self.name.invalid = not it["name"].strip()
        if not it["tiles"]:
            text(surface, "Pick at least one distance.", (fx + 130, 344), 15, BAD)

        pygame.draw.line(surface, BORDER, (0, HEIGHT - 120), (WIDTH, HEIGHT - 120))
        self.msg.draw(surface, 30, HEIGHT - 112, max_lines=3)
        for b in self.bottom:
            b.draw(surface)
