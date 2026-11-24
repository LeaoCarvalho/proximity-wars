"""In-match screen. Renders the host's state snapshots.

Drawn on a fixed 1920x1080 canvas (the app scales it to the window). Online,
the client never knows the opponent's position; offline (LocalPeer) both
wizards can be shown.
"""

import pygame

import sprites
from rules import DEFAULT_TIER, MAX_DISTANCE
from ui import BAD, GOOD, WARN, mouse_pos

GW, GH = 1920, 1080

BOARD_W = 10
TILE_X0 = 110            # centre of tile 1
TILE_PITCH = 189
TERRAIN_W = 164          # portal ring width
TERRAIN_BOTTOM = 592
RING_MID = 538           # vertical centre of the ring at TERRAIN_W
WIZARD_SCALE = 0.55      # same scale for both mages so their pixels match
WIZARD_FEET = RING_MID + 12
NUMBER_Y = 440

CARD_W, CARD_H = 416, 286    # card template size; cards are drawn at this size, then scaled
CARD_MAX_W = 410
CARD_GAP = 18
HAND_BOTTOM = 977

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
SOFT = (215, 205, 235)
FAINT = (165, 150, 190)
CURE_GREEN = (120, 255, 140)
TARGET_RED = (255, 110, 110)

# ----------------------------------------------------------------------
# Text with an outline (cached; the board redraws every frame)
# ----------------------------------------------------------------------
_fonts = {}
_texts = {}


def gfont(size, bold=True):
    key = (size, bold)
    if key not in _fonts:
        _fonts[key] = pygame.font.SysFont("calibri,segoeui,arial", size, bold=bold)
    return _fonts[key]


def render_text(s, size, color=WHITE, bold=True, outline=0, ocolor=BLACK):
    key = (str(s), size, color, bold, outline, ocolor)
    surf = _texts.get(key)
    if surf is None:
        f = gfont(size, bold)
        base = f.render(str(s), True, color)
        if outline:
            shape = f.render(str(s), True, ocolor)
            o = outline
            surf = pygame.Surface((base.get_width() + 2 * o, base.get_height() + 2 * o), pygame.SRCALPHA)
            for dx in range(-o, o + 1):
                for dy in range(-o, o + 1):
                    if dx * dx + dy * dy <= o * o + 1:
                        surf.blit(shape, (o + dx, o + dy))
            surf.blit(base, (o, o))
        else:
            surf = base
        if len(_texts) > 800:
            _texts.clear()
        _texts[key] = surf
    return surf


def draw_text(surface, s, pos, size, color=WHITE, bold=True, outline=0, anchor="center", alpha=255):
    surf = render_text(s, size, color, bold, outline)
    if alpha < 255:
        surf = surf.copy()
        surf.set_alpha(alpha)
    rect = surf.get_rect(**{anchor: pos})
    surface.blit(surf, rect)
    return rect


def fit(s, size, max_w, bold=True):
    s = str(s)
    f = gfont(size, bold)
    if f.size(s)[0] <= max_w:
        return s
    while s and f.size(s + "...")[0] > max_w:
        s = s[:-1]
    return s.rstrip() + "..."


# ----------------------------------------------------------------------
# Cards (layout measured on the 416x286 templates in assets/card_<tier>.png)
# ----------------------------------------------------------------------
_cards = {}
METER_SRC_X0, METER_SRC_STEP, METER_SRC_Y, METER_SIZE = 12, 32, 126, 29   # icon grid in distance_meter.png
METER_X0, METER_STEP, METER_Y = 14, 32.75, 241                              # where the icons go on the card
ART_BOX = pygame.Rect(14, 86, 388, 104)                                     # between the name and desc bands


def _card_key(card):
    return (card["name"], card["damage"], tuple(card["tiles"]), card.get("desc", ""),
            card.get("tier", DEFAULT_TIER), card.get("art", ""))


def _fallback_template():
    surf = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
    pygame.draw.rect(surf, (150, 110, 60), surf.get_rect(), border_radius=14)
    pygame.draw.rect(surf, BLACK, surf.get_rect(), 8, border_radius=14)
    pygame.draw.rect(surf, BLACK, (0, 28, 338, 55), border_radius=10)
    pygame.draw.rect(surf, BLACK, (14, 193, 292, 37), border_radius=10)
    pygame.draw.rect(surf, BLACK, (315, 193, 87, 77), border_radius=12)
    return surf


def render_card(card):
    """The card at template size (416x286)."""
    key = _card_key(card)
    if key in _cards:
        return _cards[key]
    template = sprites.card_template(card.get("tier", DEFAULT_TIER)) or sprites.card_template(DEFAULT_TIER)
    surf = template.copy() if template else _fallback_template()

    art = sprites.card_art(card)
    if art:
        scale = min(ART_BOX.w / art.get_width(), ART_BOX.h / art.get_height(), 1.0)
        if scale < 1.0:
            art = pygame.transform.smoothscale(
                art, (round(art.get_width() * scale), round(art.get_height() * scale)))
        surf.blit(art, art.get_rect(center=ART_BOX.center))

    draw_text(surf, fit(card["name"], 36, 300), (21, 56), 36, anchor="midleft")
    if card.get("desc"):
        draw_text(surf, fit(card["desc"], 22, 278), (22, 211), 22, anchor="midleft")
    dmg = str(card["damage"])
    draw_text(surf, dmg, (359, 231), 36 if len(dmg) < 3 else 28, outline=2)

    meter = sprites.distance_meter()
    for d in range(1, MAX_DISTANCE + 1):
        src = pygame.Rect(METER_SRC_X0 + (d - 1) * METER_SRC_STEP, METER_SRC_Y, METER_SIZE, METER_SIZE)
        dst = pygame.Rect(round(METER_X0 + (d - 1) * METER_STEP), METER_Y, METER_SIZE, METER_SIZE)
        hit = d in card["tiles"]
        if meter:
            icon = meter.subsurface(src).copy()
            if not hit:
                icon.fill((255, 255, 255, 75), special_flags=pygame.BLEND_RGBA_MULT)
            surf.blit(icon, dst)
        else:
            pygame.draw.ellipse(surf, (20, 20, 20) if hit else (90, 90, 90), dst)
            draw_text(surf, d, dst.center, 18, WHITE if hit else (150, 150, 150))
    _cards[key] = surf
    return surf


def scaled_card(card, w):
    key = (_card_key(card), w)
    if key not in _cards:
        base = render_card(card)
        h = round(w * CARD_H / CARD_W)
        _cards[key] = base if w == CARD_W else pygame.transform.smoothscale(base, (w, h))
    return _cards[key]


# ----------------------------------------------------------------------
# Screen
# ----------------------------------------------------------------------
PLAYERS = {                      # game mode -> who sits in seats 1 and 2
    "pvp": ("human", "human"),
    "bot": ("human", "bot"),
    "bot_vs_bot": ("bot", "bot"),
}
FEEDBACK_BUTTON = pygame.Rect(GW // 2 - 190, 620, 380, 70)


class GameScreen:
    size = (GW, GH)

    def __init__(self, app, ws_url, config=None, offline=False, mode="pvp", room=None, private=False):
        self.app = app
        self.ws_url = ws_url
        self.hello_config = config
        self.offline = offline
        self.mode = mode
        self.room = room
        self.private = private
        self.players = PLAYERS[mode]
        self.spectator = mode == "bot_vs_bot"
        self.hot_seat = offline and mode == "pvp"
        self.reveal = self.hot_seat   # hot seat: show the other wizard too (V toggles offline)
        self.fast = False
        self.match_id = None
        self.peer = None
        self.connect_pending = True
        self.drawn_once = False

        self.config = None
        self.state = None
        self.selected = 0
        self.status = "Starting..." if offline else "Connecting..."
        self.status_color = WARN
        self.log = []

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _connect(self):
        self.connect_pending = False
        if self.offline:
            from local_peer import LocalPeer
            self.peer = LocalPeer(self.hello_config, players=self.players)
            return
        from net_peer import NetPeer
        try:
            self.peer = NetPeer(self.ws_url)
        except Exception as exc:
            self.status, self.status_color = f"Connection failed: {exc}", BAD
            return
        hello = {"type": "hello", "mode": self.mode, "config": self.hello_config, "room": self.room,
                 "private": self.private}
        if self.app.dev_key:
            hello["dev_key"] = self.app.dev_key   # lets the server accept new attacks
        self.peer.send(hello)
        if self.mode == "pvp":
            self.status, self.status_color = "Connected. Waiting for the other player...", WARN
        else:
            self.status, self.status_color = "Connected. Starting...", WARN

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
            self.match_id = msg.get("match_id")
            self.spectator = bool(msg.get("spectator"))
            self.players = tuple(msg.get("players") or self.players)
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

    def opponent_is_bot(self):
        me = self.state["player"] if self.state else 0
        return self.players[1 - me] == "bot"

    def _refresh_status(self):
        s = self.state
        me = s["player"]
        if s["game_over"]:
            if self.spectator:
                self.status, self.status_color = f"BOT {s['winner'] + 1} WINS!", GOOD
            elif self.hot_seat:
                self.status, self.status_color = f"PLAYER {s['winner'] + 1} WINS!", GOOD
            elif s["winner"] == me:
                self.status, self.status_color = "YOU WIN!", GOOD
            else:
                self.status = "THE BOT WINS" if self.opponent_is_bot() else "YOU LOSE"
                self.status_color = BAD
        elif self.spectator:
            self.status, self.status_color = f"Bot {s['turn'] + 1}'s turn.", WARN
        elif s.get("offer") and not s["hand"]:
            self.status, self.status_color = "Pick a new card.", GOOD
        elif s["your_turn"]:
            self.status = f"Player {me + 1}'s turn." if self.hot_seat else "Your turn."
            self.status_color = GOOD
        else:
            self.status = "Bot's turn." if self.opponent_is_bot() else "Opponent's turn."
            self.status_color = WARN

    def add_log(self, line):
        if line:
            self.log.append(line)
            self.log = self.log[-3:]

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    @staticmethod
    def tile_x(i):
        return TILE_X0 + i * TILE_PITCH

    def tile_rect(self, i):
        """Clickable/highlight area of a tile: from its number down to the bottom of the terrain."""
        cx = self.tile_x(i)
        top = NUMBER_Y - 36
        return pygame.Rect(cx - 88, top, 176, TERRAIN_BOTTOM + 14 - top)

    def direction(self):
        return 1 if self.state["player"] == 0 else -1

    def target_tiles(self, card):
        """Opponent-region tiles (0-based) hit by a card from my current position."""
        pos = self.state["your_pos"]
        enemy = range(5, BOARD_W) if self.state["player"] == 0 else range(0, 5)
        return [t for t in (pos + d * self.direction() for d in card["tiles"]) if t in enemy]

    def hand_layout(self):
        s = self.state
        n = max(1, len(s["hand"]) + (1 if s.get("wait_card") else 0))
        w = min(CARD_MAX_W, (GW - 120 - CARD_GAP * (n - 1)) // n)
        h = round(w * CARD_H / CARD_W)
        total = n * w + CARD_GAP * (n - 1)
        x0 = (GW - total) // 2
        return [pygame.Rect(x0 + i * (w + CARD_GAP), HAND_BOTTOM - h, w, h) for i in range(n)]

    def offer_layout(self):
        offer = self.state.get("offer") or []
        w, gap = 250, 24
        h = round(w * CARD_H / CARD_W)
        total = len(offer) * w + gap * (len(offer) - 1)
        x0 = (GW - total) // 2
        return [pygame.Rect(x0 + i * (w + gap), 176, w, h) for i in range(len(offer))]

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def can_act(self):
        s = self.state
        if not s or s["game_over"] or self.spectator:
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

    def open_feedback(self):
        match_id = self.match_id
        self.close()
        self.app.show_feedback(match_id=match_id)

    def handle(self, event):
        s = self.state
        over = bool(s and s["game_over"])
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE or (over and event.key == pygame.K_RETURN):
                self.close()
                self.app.show_menu()
                return
            if over and event.key == pygame.K_f:
                self.open_feedback()
                return
            if self.offline and not self.spectator and self.peer and event.key == pygame.K_v:
                self.reveal = not self.reveal
            if not s or over:
                return
            if self.spectator:
                if event.key == pygame.K_s:
                    self.fast = not self.fast
                    self.send({"type": "speed", "fast": self.fast})
                return
            if self.hot_seat and self.peer and event.key == pygame.K_TAB:
                self.peer.switch()
            elif event.key in (pygame.K_LEFT, pygame.K_a):
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

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and over:
            if FEEDBACK_BUTTON.collidepoint(event.pos):
                self.open_feedback()

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and s and not self.spectator:
            for i, r in enumerate(self.offer_layout()):
                if r.collidepoint(event.pos):
                    self.send({"type": "action", "action": "pick", "index": i})
                    return
            for i, r in enumerate(self.hand_layout()[: len(s["hand"])]):
                if r.collidepoint(event.pos):
                    self.selected = i
                    return
            if s["hand"]:
                for t in self.target_tiles(s["hand"][self.selected]):
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
    def draw_background(self, surface):
        bg = sprites.background(self.size)
        if bg:
            surface.blit(bg, (0, 0))
        else:
            surface.fill((45, 20, 75))

    def draw_health(self, surface, rect, hp, max_hp, label):
        pygame.draw.rect(surface, BLACK, rect, border_radius=14)
        inner = rect.inflate(-12, -12)
        pygame.draw.rect(surface, (52, 22, 48), inner, border_radius=9)
        frac = max(0.0, min(1.0, hp / max_hp)) if max_hp else 0
        fill = inner.copy()
        fill.w = round(inner.w * frac)
        color = (22, 245, 0) if frac > 0.5 else (250, 215, 0) if frac > 0.25 else (240, 55, 45)
        if fill.w > 0:
            pygame.draw.rect(surface, color, fill, border_radius=9)
        s = f"{label}: {hp} HP"
        dark = fill.w > gfont(36, False).size(s)[0] + 40
        draw_text(surface, s, (inner.x + 18, inner.centery + 1), 36, (12, 12, 12) if dark else WHITE,
                  bold=False, anchor="midleft")

    def draw_tile(self, surface, i, s, targets, hover_tile, cures):
        cx = self.tile_x(i)
        owner = 0 if i < 5 else 1
        if i in targets:
            r = self.tile_rect(i)
            glow = pygame.Surface(r.size, pygame.SRCALPHA)
            pygame.draw.rect(glow, (230, 40, 60, 115 if i == hover_tile else 60), glow.get_rect(), border_radius=18)
            pygame.draw.rect(glow, (255, 100, 110, 230), glow.get_rect(), 4, border_radius=18)
            surface.blit(glow, r.topleft)

        active = next((c for c in cures if c["active"]), None)
        if active:
            glow = pygame.Surface((200, 110), pygame.SRCALPHA)
            for k, a in enumerate((40, 60, 85)):
                pygame.draw.ellipse(glow, (90, 255, 130, a), glow.get_rect().inflate(-k * 34, -k * 22))
            surface.blit(glow, (cx - 100, RING_MID - 55))

        img = sprites.terrain(owner, TERRAIN_W)
        if img:
            surface.blit(img, (cx - img.get_width() // 2, TERRAIN_BOTTOM - img.get_height()))
        else:
            color = (70, 140, 60) if owner == 0 else (120, 125, 120)
            pygame.draw.ellipse(surface, color, (cx - 76, RING_MID - 45, 152, 90), 14)

        if active:
            draw_text(surface, f"+{active['value']}", (cx, TERRAIN_BOTTOM + 24), 36, CURE_GREEN, outline=3)
        elif cures:
            c = cures[0]
            note = "used" if c["timer"] is None else f"in {c['timer']}"
            if s["cure_recharge"] == "all_used" and s["cure_group_timer"] is not None:
                note = f"in {s['cure_group_timer']}"
            draw_text(surface, note, (cx, TERRAIN_BOTTOM + 24), 28, (200, 195, 210), outline=2)

        draw_text(surface, i + 1, (cx, NUMBER_Y), 52, TARGET_RED if i in targets else WHITE, outline=3)

    def draw_wizard(self, surface, player_index, pos):
        cx = self.tile_x(pos)
        img = sprites.wizard(player_index, WIZARD_SCALE)
        if img:
            surface.blit(img, (cx - img.get_width() // 2, WIZARD_FEET - img.get_height()))
            # redraw the front half of the portal ring so the mage stands inside it
            ring = sprites.terrain(0 if pos < 5 else 1, TERRAIN_W)
            if ring:
                h = ring.get_height()
                front = ring.subsurface((0, h // 2, ring.get_width(), h - h // 2))
                surface.blit(front, (cx - ring.get_width() // 2, TERRAIN_BOTTOM - h + h // 2))
            return
        cy = WIZARD_FEET - 40
        pygame.draw.circle(surface, (235, 235, 245), (cx, cy), 36)
        pygame.draw.circle(surface, (30, 30, 38), (cx, cy), 36, 4)
        draw_text(surface, player_index + 1, (cx, cy), 44, (30, 30, 38))

    def draw_card(self, surface, rect, card, selected=False, hover=False, dim=False):
        img = scaled_card(card, rect.w)
        r = rect.move(0, -26 if selected else -10 if hover else 0)
        if selected:
            pygame.draw.rect(surface, WHITE, r.inflate(14, 14), 5, border_radius=16)
        surface.blit(img, r)
        if dim:
            shade = pygame.Surface(r.size, pygame.SRCALPHA)
            shade.fill((10, 0, 20, 120))
            surface.blit(shade, r)
        return r

    def draw(self, surface):
        self.draw_background(surface)
        s = self.state
        if self.connect_pending or not s:
            draw_text(surface, "PROXIMITY WARS", (GW // 2, 380), 96, outline=4)
            if self.connect_pending:
                line = "Starting offline match..." if self.offline else f"Connecting to {self.ws_url}"
                draw_text(surface, line, (GW // 2, 500), 34, SOFT, outline=2)
                self.drawn_once = True
                return
            draw_text(surface, self.status, (GW // 2, 500), 36, self.status_color, outline=2)
            draw_text(surface, "Esc: back to menu", (GW // 2, 560), 26, FAINT, outline=2)
            for i, line in enumerate(self.log):
                draw_text(surface, line, (GW // 2, 620 + i * 34), 26, SOFT, outline=2)
            return

        me, max_hp = s["player"], s["max_hp"]
        if self.spectator:
            left, right = "BOT 1", "BOT 2"
        else:
            them = "BOT" if self.opponent_is_bot() else "OPPONENT"
            left, right = ("YOU", them) if me == 0 else (them, "YOU")
        left_hp, right_hp = (s["your_hp"], s["opponent_hp"]) if me == 0 else (s["opponent_hp"], s["your_hp"])
        self.draw_health(surface, pygame.Rect(18, 25, 668, 60), left_hp, max_hp, left)
        self.draw_health(surface, pygame.Rect(GW - 18 - 668, 25, 668, 60), right_hp, max_hp, right)

        # status in the middle of the top bar ----------------------------------
        size = 44
        while size > 26 and gfont(size).size(self.status)[0] > 470:  # fit between the HP bars
            size -= 2
        draw_text(surface, self.status, (GW // 2, 46), size, self.status_color, outline=3)
        offer = s.get("offer") if s["attack_mode"] == "roguelike" else None

        # board -------------------------------------------------------------
        hand = s["hand"]
        show_targets = hand and not s["game_over"] and not self.spectator
        targets = set(self.target_tiles(hand[self.selected])) if show_targets else set()
        mouse = mouse_pos()
        hover_tile = next((t for t in targets if self.tile_rect(t).collidepoint(mouse)), None)
        cures_by_tile = {}
        for c in s["cures"]:
            if c["active"] or s["cure_respawn"] == "same":
                cures_by_tile.setdefault(c["tile"], []).append(c)
        for i in range(BOARD_W):
            self.draw_tile(surface, i, s, targets, hover_tile, cures_by_tile.get(i, []))

        if self.spectator and s.get("positions"):
            for i, pos in enumerate(s["positions"]):
                self.draw_wizard(surface, i, pos)
        else:
            if self.offline and self.reveal and self.peer:
                self.draw_wizard(surface, 1 - me, self.peer.opponent_pos())
            self.draw_wizard(surface, me, s["your_pos"])

        # hand ----------------------------------------------------------------
        rects = self.hand_layout()
        hovered = next((i for i, r in enumerate(rects[: len(hand)]) if r.collidepoint(mouse)), None)
        for i, card in enumerate(hand):
            if self.spectator:
                self.draw_card(surface, rects[i], card)
            else:
                self.draw_card(surface, rects[i], card, selected=i == self.selected, hover=i == hovered)
        if not hand:
            draw_text(surface, "No cards in hand.", (GW // 2, 840), 34, FAINT, outline=2)
        if s.get("wait_card"):
            r = self.draw_card(surface, rects[-1], s["wait_card"], dim=True)
            draw_text(surface, "WAITING CARD (shared)", (r.centerx, r.y - 18), 24, (255, 220, 120), outline=2)

        # roguelike offer -----------------------------------------------------
        if offer and not self.spectator:
            boxes = self.offer_layout()
            panel = boxes[0].unionall(boxes).inflate(60, 96).move(0, -16)
            shade = pygame.Surface(panel.size, pygame.SRCALPHA)
            pygame.draw.rect(shade, (14, 6, 28, 245), shade.get_rect(), border_radius=20)
            pygame.draw.rect(shade, (120, 255, 150, 255), shade.get_rect(), 3, border_radius=20)
            surface.blit(shade, panel.topleft)
            more = s.get("offers_pending", 0)
            extra = f" ({more} more after this)" if more else ""
            draw_text(surface, f"Choose a card to add to your hand{extra}", (GW // 2, panel.y + 26), 28,
                      CURE_GREEN, outline=2)
            for k, (r, card) in enumerate(zip(boxes, offer)):
                self.draw_card(surface, r, card, hover=r.collidepoint(mouse))

        # controls --------------------------------------------------------------
        if self.spectator:
            speed = "fast" if self.fast else "normal"
            hint = f"S: bot speed ({speed})    Esc: menu"
        else:
            hint = "A/D: move    H: cure    1-9 / click: card    Space / click a red tile: cast    Esc: menu"
            if self.hot_seat:
                hint += "    Tab: switch player"
            if self.offline:
                hint += "    V: show/hide opponent"
        draw_text(surface, hint, (GW // 2, 1052), 22, FAINT, outline=2)

        if s["game_over"]:
            overlay = pygame.Surface((GW, GH), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            surface.blit(overlay, (0, 0))
            draw_text(surface, self.status, (GW // 2, 440), 120, self.status_color, outline=5)
            draw_text(surface, "Enter or Esc: back to menu", (GW // 2, 560), 34, SOFT, outline=2)
            hover = FEEDBACK_BUTTON.collidepoint(mouse)
            pygame.draw.rect(surface, (70, 40, 110) if hover else (45, 24, 75), FEEDBACK_BUTTON, border_radius=16)
            pygame.draw.rect(surface, WHITE, FEEDBACK_BUTTON, 3, border_radius=16)
            draw_text(surface, "Send feedback (F)", FEEDBACK_BUTTON.center, 34)
