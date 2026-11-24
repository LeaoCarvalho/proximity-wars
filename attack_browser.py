"""Pick attacks that were played before (stored in the database) and add them to the attack editor.

The list comes from the Turso database in .env when this computer has one,
otherwise from the server's GET /attacks.
"""

import json
import threading
import urllib.error
import urllib.request

import pygame

from metrics import MetricsStore, attack_id
from rules import ConfigError, validate_attacks
from ui import (
    ACCENT, BAD, BG, BORDER, Button, DIM, GOOD, HEIGHT, MUTED, PANEL, PANEL_HI, TEXT, TextField, WARN, WIDTH,
    fit_text, text,
)

TIER_COLORS = {"bronze": (205, 140, 90), "silver": (190, 198, 210), "gold": (235, 200, 90)}


def fetch_stored_attacks(http_url, timeout=10):
    """[(entry, attack)] of every stored attack, and where they came from. Raises OSError / ValueError."""
    store = MetricsStore()   # uses the database from .env if this computer has one
    if store.db is not None:
        entries, source = store.attacks(), "the database"
    else:
        with urllib.request.urlopen(http_url.rstrip("/") + "/attacks", timeout=timeout) as resp:
            entries = json.loads(resp.read().decode("utf-8"))
        source = "the server"
    out = []
    for entry in entries if isinstance(entries, list) else []:
        try:
            attack = validate_attacks([entry["attack"]])[0]   # never trust stored data blindly
        except (ConfigError, KeyError, TypeError):
            continue
        out.append((entry, attack))
    return out, source


class AttackBrowser:
    LIST_X, LIST_Y, LIST_W, ROW_H = 30, 118, 640, 32
    LIST_ROWS = 14

    def __init__(self, app, editor):
        self.app = app
        self.editor = editor
        self.entries = []          # [(entry, attack)]
        self.checked = set()       # attack ids
        self.focus = None          # attack id shown in the preview
        self.scroll = 0
        self.status, self.status_color = "", MUTED
        self.loading = False
        self.result = None
        self.search = TextField(w=300, placeholder="search by name").place(self.LIST_X + 70, 66)
        self.add_button = Button("Add selected", self.add, primary=True)
        self.bottom = [
            Button("Back", self.back),
            Button("Refresh", self.refresh),
            Button("Select shown", self.select_shown),
            Button("Clear", lambda: self.checked.clear()),
            Button("Replace list with selected", self.replace),
            self.add_button,
        ]
        x = 30
        for b in self.bottom:
            b.place(x, HEIGHT - 52)
            x += b.rect.w + 8
        self.refresh()

    # data ----------------------------------------------------------------
    def refresh(self):
        if self.loading:
            return
        self.loading = True
        self.status, self.status_color = "Loading attacks...", WARN
        url = self.app.http_url()

        def work():
            try:
                self.result = ("ok",) + fetch_stored_attacks(url)
            except urllib.error.HTTPError as exc:
                self.result = ("error", f"the server answered {exc.code}")
            except (OSError, ValueError) as exc:
                self.result = ("error", str(getattr(exc, "reason", exc)) or exc.__class__.__name__)

        threading.Thread(target=work, daemon=True).start()

    def update(self):
        if self.result is None:
            return
        result, self.result, self.loading = self.result, None, False
        if result[0] == "error":
            self.status, self.status_color = f"Could not load the attacks: {result[1]}", BAD
            return
        _, entries, source = result
        self.entries = entries
        ids = {e["id"] for e, _ in entries}
        self.checked &= ids
        if self.focus not in ids:
            self.focus = entries[0][0]["id"] if entries else None
        self.scroll = 0
        if entries:
            self.status, self.status_color = f"{len(entries)} different attack(s) from {source}.", GOOD
        else:
            self.status, self.status_color = (f"No attacks stored in {source} yet. They are saved "
                                              "when a match ends."), MUTED

    def shown(self):
        query = self.search.value.strip().lower()
        return [(e, a) for e, a in self.entries if query in a["name"].lower()]

    def selected_attacks(self):
        return [a for e, a in self.entries if e["id"] in self.checked]

    # actions ---------------------------------------------------------------
    def select_shown(self):
        self.checked.update(e["id"] for e, _ in self.shown())

    def add(self):
        picked = self.selected_attacks()
        if not picked:
            self.status, self.status_color = "Click attacks to select them first.", BAD
            return
        added = self.editor.add_attacks(picked)
        skipped = len(picked) - added
        if not added:
            self.editor.msg.info("Those attacks are already in your list.")
        else:
            self.editor.msg.info(f"Added {added} attack(s) from the database"
                                 + (f", skipped {skipped} already in your list." if skipped else "."))
        self.back()

    def replace(self):
        picked = self.selected_attacks()
        if not picked:
            self.status, self.status_color = "Click attacks to select them first.", BAD
            return
        self.editor.set_attacks(picked, "the database")
        self.back()

    def back(self):
        self.app.set_screen(self.editor)

    # events / drawing ------------------------------------------------------
    def row_rect(self, visible_index):
        return pygame.Rect(self.LIST_X, self.LIST_Y + visible_index * self.ROW_H, self.LIST_W, self.ROW_H - 3)

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            TextField.blur()
            shown = self.shown()
            for vi in range(self.LIST_ROWS):
                i = self.scroll + vi
                if i < len(shown) and self.row_rect(vi).collidepoint(event.pos):
                    aid = shown[i][0]["id"]
                    self.focus = aid
                    self.checked.symmetric_difference_update({aid})
                    return
        if event.type == pygame.MOUSEWHEEL:
            max_scroll = max(0, len(self.shown()) - self.LIST_ROWS)
            self.scroll = min(max_scroll, max(0, self.scroll - event.y))
            return
        for w in [self.search, *self.bottom]:
            if w.handle(event):
                self.scroll = 0 if w is self.search else self.scroll
                return
        if TextField.focused is self.search and event.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
            self.scroll = 0
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.back()

    def draw(self, surface):
        surface.fill(BG)
        text(surface, "ATTACKS FROM THE DATABASE", (WIDTH // 2, 18), 34, bold=True, center=True)
        text(surface, "Search", (self.LIST_X, 73), 18)
        self.search.draw(surface)
        shown = self.shown()
        text(surface, f"{len(self.checked)} selected", (self.LIST_X + self.LIST_W, 73), 17, MUTED, right=True)

        for vi in range(self.LIST_ROWS):
            i = self.scroll + vi
            if i >= len(shown):
                break
            entry, attack = shown[i]
            r = self.row_rect(vi)
            on = entry["id"] in self.checked
            pygame.draw.rect(surface, PANEL_HI if on else PANEL, r, border_radius=5)
            if entry["id"] == self.focus:
                pygame.draw.rect(surface, ACCENT, r, 1, border_radius=5)
            box = pygame.Rect(r.x + 8, r.y + 7, 15, 15)
            pygame.draw.rect(surface, ACCENT if on else BORDER, box, 0 if on else 1, border_radius=3)
            text(surface, fit_text(attack["name"], 17, 200), (r.x + 32, r.y + 6), 17)
            text(surface, f"{attack['damage']} dmg", (r.x + 240, r.y + 7), 16, MUTED)
            tiles = ",".join(str(t) for t in attack["tiles"])
            text(surface, fit_text(tiles, 15, 120), (r.x + 320, r.y + 8), 15, DIM)
            text(surface, attack["tier"], (r.x + 450, r.y + 7), 16, TIER_COLORS.get(attack["tier"], TEXT))
            n = entry.get("matches") or 0
            text(surface, f"{n} match{'es' if n != 1 else ''}", (r.right - 10, r.y + 7), 15, DIM, right=True)
        if not shown and self.entries:
            text(surface, "No attack matches the search.", (self.LIST_X, self.LIST_Y + 6), 17, DIM)
        if len(shown) > self.LIST_ROWS:
            text(surface, "scroll for more", (self.LIST_X + self.LIST_W, self.LIST_Y - 20), 14, DIM, right=True)

        focus = next(((e, a) for e, a in self.entries if e["id"] == self.focus), None)
        if focus:
            from game import scaled_card
            entry, attack = focus
            px, w = 700, 370
            surface.blit(scaled_card(attack, w), (px, self.LIST_Y))
            y = self.LIST_Y + round(w * 286 / 416) + 14
            n = entry.get("matches") or 0
            text(surface, f"Played in {n} match{'es' if n != 1 else ''}", (px, y), 17, MUTED)
            if entry.get("last_used"):
                text(surface, "Last played " + entry["last_used"].replace("T", " ").replace("Z", " UTC"),
                     (px, y + 24), 16, DIM)
            in_list = attack_id(attack) in self.editor.item_ids()
            if in_list:
                text(surface, "Already in your attack list", (px, y + 48), 16, WARN)

        self.add_button.enabled = bool(self.checked)
        pygame.draw.line(surface, BORDER, (0, HEIGHT - 96), (WIDTH, HEIGHT - 96))
        text(surface, fit_text(self.status, 16, WIDTH - 60), (30, HEIGHT - 86), 16, self.status_color)
        for b in self.bottom:
            b.draw(surface)
