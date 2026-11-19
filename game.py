"""In-match screen. Renders the server's state snapshots; never knows the opponent's position."""

import pygame

from rules import CURE_MODE_NAMES, MAX_DISTANCE
from ui import (
    BAD, BG, BORDER, CURE, DIM, GOOD, HEIGHT, MUTED, P1_COLOR, P2_COLOR, PANEL, PANEL_HI, TEXT,
    WARN, WIDTH, fit_text, font, text, wrap_text,
)

BOARD_W = 10
TILE = 88
BOARD_X = (WIDTH - BOARD_W * TILE) // 2
BOARD_Y = 190
HAND_Y = 400
CARD_H = 122
EXTRA_Y = 530


class GameScreen:
    def __init__(self, app, ws_url, config=None):
        self.app = app
        self.ws_url = ws_url
        self.hello_config = config
        self.peer = None
        self.connect_pending = True
        self.drawn_once = False

        self.config = None
        self.state = None
        self.selected = 0
        self.status = "Connecting..."
        self.status_color = WARN
        self.log = []
        self.mouse = (0, 0)

    # ------------------------------------------------------------------
    # Network
    # ------------------------------------------------------------------
    def _connect(self):
        from net_peer import NetPeer
        self.connect_pending = False
        try:
            self.peer = NetPeer(self.ws_url)
        except Exception as exc:
            self.status, self.status_color = f"Connection failed: {exc}", BAD
            return
        self.peer.send({"type": "hello", "config": self.hello_config})
        self.status, self.status_color = "Connected. Waiting for the other player...", WARN

    def send(self, message):
        if self.peer and self.peer.running:
            self.peer.send(message)

    def close(self):
        if self.peer:
            self.send({"type": "disconnect"})
            self.peer.close()
            self.peer = None

    def on_message(self, msg):
        t = msg.get("type")
        if t in ("waiting", "info"):
            self.status, self.status_color = msg.get("message", ""), WARN
            if t == "info":
                self.add_log(msg.get("message", ""))
        elif t == "config_error":
            self.close()
            self.app.config_rejected(msg.get("errors", []), self.hello_config)
        elif t == "match_start":
            self.config = msg["config"]
            self.add_log(f"You are Player {msg['player'] + 1}.")
        elif t == "state":
            self.state = msg
            hand = msg.get("hand", [])
            self.selected = max(0, min(self.selected, len(hand) - 1))
            for e in msg.get("events", []):
                self.add_log(e)
            self._refresh_status()
        elif t == "error":
            self.status, self.status_color = msg.get("message", "Invalid action."), BAD
        elif t == "disconnect":
            if not (self.state and self.state["game_over"]):
                self.status, self.status_color = msg.get("message", "Disconnected."), BAD
            if self.peer:
                self.peer.running = False

    def _refresh_status(self):
        s = self.state
        if s["game_over"]:
            won = s["winner"] == s["player"]
            self.status, self.status_color = ("YOU WIN!" if won else "YOU LOSE"), (GOOD if won else BAD)
        elif s.get("offer") and not s["hand"]:
            self.status, self.status_color = "Pick a new card.", GOOD
        elif s["your_turn"]:
            self.status, self.status_color = "Your turn.", GOOD
        else:
            self.status, self.status_color = "Opponent's turn.", WARN

    def add_log(self, line):
        if line:
            self.log.append(line)
            self.log = self.log[-3:]

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------
    def tile_rect(self, i):
        return pygame.Rect(BOARD_X + i * TILE, BOARD_Y, TILE - 2, TILE - 2)

    def direction(self):
        return 1 if self.state["player"] == 0 else -1

    def target_tiles(self, card):
        """Opponent-region tiles (0-based) hit by a card from my current position."""
        pos = self.state["your_pos"]
        enemy = range(5, BOARD_W) if self.state["player"] == 0 else range(0, 5)
        out = []
        for d in card["tiles"]:
            t = pos + d * self.direction()
            if t in enemy:
                out.append(t)
        return out

    def hand_layout(self):
        s = self.state
        n = len(s["hand"]) + (1 if s.get("wait_card") else 0)
        n = max(n, 1)
        gap = 10
        w = min(240, (WIDTH - 60 - gap * (n - 1)) // n)
        total = n * w + gap * (n - 1)
        x0 = (WIDTH - total) // 2
        return [pygame.Rect(x0 + i * (w + gap), HAND_Y, w, CARD_H) for i in range(n)]

    def offer_layout(self):
        offer = self.state.get("offer") or []
        w, gap = 210, 10
        total = len(offer) * w + gap * (len(offer) - 1)
        x0 = (WIDTH - total) // 2
        return [pygame.Rect(x0 + i * (w + gap), EXTRA_Y + 22, w, 100) for i in range(len(offer))]

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def can_act(self):
        s = self.state
        if not s or s["game_over"]:
            return False
        if not s["your_turn"]:
            self.status, self.status_color = "It is not your turn.", BAD
            return False
        return True

    def attack(self):
        if not self.can_act():
            return
        if not self.state["hand"]:
            self.status, self.status_color = "You have no cards.", BAD
            return
        self.send({"type": "action", "action": "attack", "card": self.selected})

    def handle(self, event):
        s = self.state
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE or (s and s["game_over"] and event.key == pygame.K_RETURN):
                self.close()
                self.app.show_menu()
                return
            if not s or s["game_over"]:
                return
            if event.key in (pygame.K_LEFT, pygame.K_a):
                if self.can_act():
                    self.send({"type": "action", "action": "move", "direction": -1})
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                if self.can_act():
                    self.send({"type": "action", "action": "move", "direction": 1})
            elif event.key == pygame.K_h:
                if self.can_act():
                    self.send({"type": "action", "action": "heal"})
            elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
                self.attack()
            elif pygame.K_1 <= event.key <= pygame.K_9:
                i = event.key - pygame.K_1
                if i < len(s["hand"]):
                    self.selected = i

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and s and not s["game_over"]:
            for i, r in enumerate(self.offer_layout()):
                if r.collidepoint(event.pos):
                    self.send({"type": "action", "action": "pick", "index": i})
                    return
            for i, r in enumerate(self.hand_layout()[: len(s["hand"])]):
                if r.collidepoint(event.pos):
                    self.selected = i
                    return
            if s["hand"]:
                targets = self.target_tiles(s["hand"][self.selected])
                for t in targets:
                    if self.tile_rect(t).collidepoint(event.pos):
                        self.attack()
                        return

    def update(self):
        if self.connect_pending:
            if self.drawn_once:  # connect after the "Connecting..." frame is on screen
                self._connect()
            return
        if not self.peer:
            return
        for msg in self.peer.poll():
            self.on_message(msg)
        if self.peer and not self.peer.running and not (self.state and self.state["game_over"]):
            if self.status_color != BAD:
                self.status, self.status_color = "Disconnected from host.", BAD

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def draw_health(self, surface, x, y, hp, max_hp, label):
        pygame.draw.rect(surface, (45, 45, 52), (x, y, 360, 28), border_radius=7)
        pygame.draw.rect(surface, (200, 70, 70), (x, y, max(0, int(360 * hp / max_hp)), 28), border_radius=7)
        text(surface, f"{label}: {hp} / {max_hp} HP", (x + 10, y + 3), 20)

    def draw_card(self, surface, rect, card, selected=False, dim=False, label=None):
        pygame.draw.rect(surface, PANEL_HI if selected else PANEL, rect, border_radius=10)
        pygame.draw.rect(surface, (180, 200, 240) if selected else BORDER, rect, 2 if selected else 1,
                         border_radius=10)
        x, w = rect.x + 10, rect.w - 20
        color = DIM if dim else TEXT
        title = f"{label} {card['name']}" if label else card["name"]
        text(surface, fit_text(title, 18, w, bold=True), (x, rect.y + 8), 18, color, bold=True)
        text(surface, f"Damage: {card['damage']}", (x, rect.y + 32), 15, MUTED)
        # distance strip
        box = max(8, min(18, (w - 2 * (MAX_DISTANCE - 1)) // MAX_DISTANCE))
        for d in range(1, MAX_DISTANCE + 1):
            r = pygame.Rect(x + (d - 1) * (box + 2), rect.y + 54, box, box)
            on = d in card["tiles"]
            pygame.draw.rect(surface, (210, 85, 85) if on else (50, 52, 62), r, border_radius=3)
            if box >= 14:
                text(surface, d, (r.centerx, r.y + 1), 12, TEXT if on else DIM, center=True)
        desc = wrap_text(card.get("desc", ""), 14, w)[: max(0, (rect.h - 78) // 17)]
        for i, line in enumerate(desc):
            text(surface, fit_text(line, 14, w), (x, rect.y + 78 + i * 17), 14, DIM)

    def draw(self, surface):
        if self.connect_pending:
            surface.fill(BG)
            text(surface, "Connecting to", (WIDTH // 2, 300), 22, MUTED, center=True)
            text(surface, self.ws_url, (WIDTH // 2, 330), 22, center=True)
            self.drawn_once = True
            return

        surface.fill(BG)
        text(surface, "PROXIMITY WARS", (WIDTH // 2, 16), 42, bold=True, center=True)
        s = self.state
        if not s:
            text(surface, self.status, (WIDTH // 2, 320), 22, self.status_color, center=True)
            text(surface, "Esc: back to menu", (WIDTH // 2, 360), 16, DIM, center=True)
            for i, line in enumerate(self.log):
                text(surface, line, (WIDTH // 2, 400 + i * 20), 16, MUTED, center=True)
            return

        me, max_hp = s["player"], s["max_hp"]
        left, right = ("YOU", "OPPONENT") if me == 0 else ("OPPONENT", "YOU")
        left_hp, right_hp = (s["your_hp"], s["opponent_hp"]) if me == 0 else (s["opponent_hp"], s["your_hp"])
        self.draw_health(surface, 55, 80, left_hp, max_hp, left)
        self.draw_health(surface, WIDTH - 415, 80, right_hp, max_hp, right)
        text(surface, f"Opponent holds {s['opponent_hand_size']} card(s)", (WIDTH // 2, 86), 15, DIM, center=True)

        # board -----------------------------------------------------------
        hand = s["hand"]
        targets = set(self.target_tiles(hand[self.selected])) if hand and not s["game_over"] else set()
        hover_tile = next((t for t in targets if self.tile_rect(t).collidepoint(pygame.mouse.get_pos())), None)
        cures_by_tile = {}
        for c in s["cures"]:
            if c["active"] or s["cure_respawn"] == "same":
                cures_by_tile.setdefault(c["tile"], []).append(c)

        for i in range(BOARD_W):
            r = self.tile_rect(i)
            base = P1_COLOR if i < 5 else P2_COLOR
            if i in targets:
                base = (150, 70, 70) if hover_tile is None else (190, 85, 85)
            pygame.draw.rect(surface, base, r, border_radius=6)
            for c in cures_by_tile.get(i, []):
                if c["active"]:
                    pygame.draw.rect(surface, CURE, r, 4, border_radius=6)
                    text(surface, f"+{c['value']}", (r.centerx, r.bottom - 26), 18, (135, 245, 160),
                         bold=True, center=True)
                    break
            else:
                if cures_by_tile.get(i):
                    c = cures_by_tile[i][0]
                    pygame.draw.rect(surface, (80, 95, 85), r, 2, border_radius=6)
                    note = "used" if c["timer"] is None else f"in {c['timer']}"
                    if s["cure_recharge"] == "all_used" and s["cure_group_timer"] is not None:
                        note = f"in {s['cure_group_timer']}"
                    text(surface, note, (r.centerx, r.bottom - 22), 14, DIM, center=True)
            text(surface, i + 1, (r.x + 6, r.y + 4), 15, MUTED)

        text(surface, "YOUR REGION" if me == 0 else "OPPONENT REGION", (BOARD_X, BOARD_Y - 22), 15, (170, 195, 220))
        text(surface, "OPPONENT REGION" if me == 0 else "YOUR REGION", (BOARD_X + 5 * TILE, BOARD_Y - 22), 15,
             (220, 175, 200))

        cx = BOARD_X + s["your_pos"] * TILE + TILE // 2
        cy = BOARD_Y + TILE // 2 - 8
        pygame.draw.circle(surface, (235, 235, 245), (cx, cy), 22)
        pygame.draw.circle(surface, (30, 30, 38), (cx, cy), 22, 3)
        text(surface, me + 1, (cx, cy - 17), 30, (30, 30, 38), bold=True, center=True)

        # cure info line ---------------------------------------------------
        mode = CURE_MODE_NAMES.get(self.config["cure"]["mode"], "") if self.config else ""
        info = [f"Cure: {mode}", f"cures left this turn: {max(0, s['cures_left_this_turn'])}",
                "curing ends your turn" if s["cure_ends_turn"] else "curing is a free action"]
        waiting = [c for c in s["cures"] if not c["active"]]
        if s["cure_respawn"] == "random" and waiting:
            timers = [c["timer"] for c in waiting if c["timer"] is not None]
            info.append(f"next cure appears in {min(timers)} turn(s)" if timers else "no cure will come back")
        elif s["cure_recharge"] == "all_used" and s["cure_group_timer"] is not None:
            info.append(f"cures recharge in {s['cure_group_timer']} turn(s)")
        elif s["cures"] and not any(c["active"] for c in s["cures"]) and s["cure_group_timer"] is None:
            if all(c["timer"] is None for c in s["cures"]):
                info.append("all cures used up")
        elif not s["cures"]:
            info.append("you have no cures")
        text(surface, "  |  ".join(info), (WIDTH // 2, BOARD_Y + TILE + 10), 15, MUTED, center=True)

        # status ----------------------------------------------------------
        text(surface, self.status, (WIDTH // 2, 318), 24, self.status_color, bold=True, center=True)
        hint = "A/D or arrows: move    H: cure    1-9 / click: pick card    Space or click a red tile: cast    Esc: menu"
        text(surface, hint, (WIDTH // 2, 352), 15, DIM, center=True)

        # hand ------------------------------------------------------------
        rects = self.hand_layout()
        for i, card in enumerate(hand):
            self.draw_card(surface, rects[i], card, selected=i == self.selected, label=f"{i + 1}.")
        if not hand:
            text(surface, "No cards in hand.", (WIDTH // 2, HAND_Y + 50), 18, DIM, center=True)
        if s.get("wait_card"):
            r = rects[-1]
            text(surface, "WAITING CARD (shared)", (r.x, HAND_Y - 18), 13, WARN)
            self.draw_card(surface, r, s["wait_card"], dim=True)

        # roguelike offer -------------------------------------------------
        if s["attack_mode"] == "roguelike":
            offer = s.get("offer")
            if offer:
                more = s.get("offers_pending", 0)
                extra = f" ({more} more after this)" if more else ""
                text(surface, f"Choose a card to add to your hand{extra} - click one:", (WIDTH // 2, EXTRA_Y),
                     17, GOOD, center=True)
                for r, card in zip(self.offer_layout(), offer):
                    self.draw_card(surface, r, card)
            else:
                text(surface, f"New card choice after {s['discards_until_pick']} more used card(s).",
                     (WIDTH // 2, EXTRA_Y), 16, DIM, center=True)

        # log -------------------------------------------------------------
        log_y = HEIGHT - 6 - 18 * len(self.log)
        for i, line in enumerate(self.log):
            color = TEXT if i == len(self.log) - 1 else DIM
            text(surface, line, (20, log_y + i * 18), 15, color)

        if s["game_over"]:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            surface.blit(overlay, (0, 0))
            won = s["winner"] == me
            text(surface, "YOU WIN!" if won else "YOU LOSE", (WIDTH // 2, 270), 56, TEXT, bold=True, center=True)
            text(surface, "Enter: back to menu    Esc: menu", (WIDTH // 2, 345), 20, MUTED, center=True)
