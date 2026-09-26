
import random
from dataclasses import dataclass

import pygame

# ============================================================
# Proximity Wars
# Direct peer-to-peer prototype:
#   - One player starts as HOST and listens.
#   - The other JOINs directly to the host's IP/port.
#   - No central game server is required.
#
# Important networking design:
#   Each peer keeps its own private position. Only public facts
#   (health, action result, winner) are sent over the connection.
#   The host is a session coordinator/validator, not a game server.
#   For internet play, the host normally needs a reachable port
#   (port-forwarding or a VPN such as Tailscale/ZeroTier).
# ============================================================

WIDTH, HEIGHT = 1100, 720
FPS = 60

BOARD_W = 10
TILE = 88
BOARD_X = (WIDTH - BOARD_W * TILE) // 2
BOARD_Y = 235

MAX_HP = 100

# A "player region" is half the board. Players may never enter
# the opponent's region. The boundary is between indices 4 and 5.
# Healing tiles are the innermost tile in each player's region.
HEAL_TILES = {4: 35, 5: 35}

# Weapons are intentionally easy to tune for playtesting.
# range = maximum distance; damage = HP removed on a hit.
WEAPONS = [
    {"name": "Pulse", "range": 1, "damage": 30, "desc": "Short / heavy"},
    {"name": "Bolt", "range": 2, "damage": 22, "desc": "Reliable"},
    {"name": "Wave", "range": 3, "damage": 16, "desc": "Longer reach"},
    {"name": "Snipe", "range": 4, "damage": 12, "desc": "Maximum range"},
]


@dataclass
class PlayerState:
    pos: int
    hp: int = MAX_HP


class Game:
    def __init__(self, is_host):
        self.is_host = is_host
        self.my_index = 0 if is_host else 1
        self.enemy_index = 1 - self.my_index

        # Host owns initial random placement; joiner receives its own
        # private placement from the host during handshake.
        self.my = None
        self.enemy_hp = MAX_HP
        self.enemy_alive = True

        self.peer = None
        self.connected = False
        self.connection_error = None
        self.status = "Starting..."
        self.last_result = ""
        self.turn = 0
        self.my_turn = True if is_host else False
        self.game_over = False
        self.winner = None

        self.font = pygame.font.SysFont("arial", 22)
        self.small = pygame.font.SysFont("arial", 16)
        self.big = pygame.font.SysFont("arial", 36, bold=True)
        self.title = pygame.font.SysFont("arial", 48, bold=True)

        self.setup_board()

    def setup_board(self):
        if self.is_host:
            # Host lives in 0..4; joiner in 5..9.
            self.my = PlayerState(random.randint(0, 3))
            enemy_start = random.randint(6, 9)
            self.private_enemy_start = enemy_start
        else:
            # Temporary value until handshake.
            self.my = PlayerState(9)
            self.private_enemy_start = None

    def attach_peer(self, peer):
        self.peer = peer
        self.connected = True
        if self.is_host:
            # Tell joiner only their own starting position and public data.
            self.enemy_pos = self.private_enemy_start
            peer.send({
                "type": "hello",
                "your_pos": self.private_enemy_start,
                "your_hp": MAX_HP,
                "enemy_hp": self.my.hp,
                "turn": 0,
                "your_turn": False,
            })
            self.status = "Connected. Your turn."
        else:
            self.status = "Connected. Waiting for host..."

    def send(self, msg):
        if self.peer and self.peer.running:
            self.peer.send(msg)

    def distance(self, a, b):
        return abs(a - b)

    def legal_move(self, player_index, pos, direction):
        new_pos = pos + direction
        if player_index == 0:
            return 0 <= new_pos <= 4
        return 5 <= new_pos <= 9

    def local_move(self, direction):
        if self.game_over or not self.my_turn or not self.connected:
            return
        if not self.legal_move(self.my_index, self.my.pos, direction):
            self.status = "You cannot enter the enemy region."
            return

        self.my.pos += direction

        if self.is_host:
            # Do not reveal the host's new position.
            self.turn += 1
            self.send({
                "type": "opponent_moved",
                "enemy_hp": self.enemy_hp,
                "turn": self.turn,
                "your_turn": True,
            })
            self.my_turn = False
            self.status = "You moved. Waiting for opponent..."
        else:
            self.send({"type": "action", "action": "move", "direction": direction})
            self.my_turn = False
            self.status = "Move sent. Waiting for opponent..."

    def local_heal(self):
        if self.game_over or not self.my_turn or not self.connected:
            return
        amount = HEAL_TILES.get(self.my.pos)
        if not amount:
            self.status = "You can only heal on the glowing tile."
            return
        if self.my.hp >= MAX_HP:
            self.status = "You are already at full health."
            return

        self.my.hp = min(MAX_HP, self.my.hp + amount)

        if self.is_host:
            self.turn += 1
            self.send({
                "type": "heal_result",
                "your_hp": self.enemy_hp,
                "enemy_hp": self.my.hp,
                "turn": self.turn,
                "your_turn": True,
            })
            self.my_turn = False
            self.status = "You healed. Waiting for opponent..."
        else:
            self.send({"type": "action", "action": "heal"})
            self.my_turn = False
            self.status = "Heal sent. Waiting for opponent..."

    def local_attack(self, weapon_id):
        if self.game_over or not self.my_turn or not self.connected:
            return
        if not 0 <= weapon_id < len(WEAPONS):
            return

        weapon = WEAPONS[weapon_id]

        if self.is_host:
            # Host can calculate the result because it keeps both private
            # positions. The result contains no position information.
            d = self.distance(self.my.pos, self.enemy_pos)
            hit = d <= weapon["range"]
            damage = weapon["damage"] if hit else 0
            if hit:
                self.enemy_hp = max(0, self.enemy_hp - damage)

            self.turn += 1
            self.send({
                "type": "attack_result",
                "weapon": weapon_id,
                "hit": hit,
                "damage": damage,
                "your_hp": self.enemy_hp,
                "enemy_hp": self.my.hp,
                "turn": self.turn,
                "your_turn": True,
                "game_over": self.enemy_hp <= 0,
                "winner": 0 if self.enemy_hp <= 0 else None,
            })

            if self.enemy_hp <= 0:
                self.game_over = True
                self.winner = 0
                self.status = "You win!"
            else:
                self.my_turn = False
                self.status = f"{weapon['name']} fired. Waiting for opponent..."
        else:
            self.send({
                "type": "action",
                "action": "attack",
                "weapon": weapon_id,
            })
            self.my_turn = False
            self.status = f"{weapon['name']} fired. Waiting for result..."

    # Host validates the opponent's action against the host's private
    # position and sends only the information the opponent is allowed to know.
    def host_process_action(self, msg):
        if not self.is_host or self.game_over:
            return
        if msg.get("type") != "action":
            return

        action = msg.get("action")
        # The joiner's position is private to the host and is updated only
        # by the joiner's own move commands. It is never broadcast.
        if action == "move":
            direction = int(msg.get("direction", 0))
            if self.legal_move(1, self.enemy_pos, direction):
                self.enemy_pos += direction
                self.turn += 1
                self.send({
                    "type": "move_result",
                    "your_pos": self.enemy_pos,
                    "enemy_hp": self.my.hp,
                    "turn": self.turn,
                    "your_turn": True,
                })
                self.my_turn = False
                self.status = "Opponent moved. Your turn."
            else:
                self.send({"type": "error", "message": "Illegal move."})
                self.send({"type": "turn", "your_turn": True})
                return

        elif action == "heal":
            amount = HEAL_TILES.get(self.enemy_pos)
            if amount and self.enemy_hp < MAX_HP:
                self.enemy_hp = min(MAX_HP, self.enemy_hp + amount)
                self.turn += 1
                self.send({
                    "type": "heal_result",
                    "your_hp": self.enemy_hp,
                    "enemy_hp": self.my.hp,
                    "turn": self.turn,
                    "your_turn": True,
                })
                self.my_turn = False
                self.status = "Opponent healed. Your turn."
            else:
                self.send({"type": "error", "message": "Illegal heal."})
                self.send({"type": "turn", "your_turn": True})

        elif action == "attack":
            weapon_id = int(msg.get("weapon", -1))
            if not 0 <= weapon_id < len(WEAPONS):
                return
            weapon = WEAPONS[weapon_id]
            d = self.distance(self.enemy_pos, self.my.pos)
            hit = d <= weapon["range"]
            damage = weapon["damage"] if hit else 0
            if hit:
                self.my.hp = max(0, self.my.hp - damage)

            self.turn += 1
            result = {
                "type": "attack_result",
                "weapon": weapon_id,
                "hit": hit,
                "damage": damage,
                "your_hp": self.enemy_hp,
                "enemy_hp": self.my.hp,
                "turn": self.turn,
                "your_turn": True,
                "game_over": self.my.hp <= 0,
                "winner": 1 if self.my.hp <= 0 else None,
            }
            self.send(result)

            if self.my.hp <= 0:
                self.game_over = True
                self.winner = 1
                self.status = "You were defeated."
            else:
                self.my_turn = False
                self.status = "Opponent attacked. Your turn."

    def handle_message(self, msg):
        t = msg.get("type")

        if t == "hello":
            if not self.is_host:
                self.my.pos = int(msg["your_pos"])
                self.enemy_hp = int(msg["enemy_hp"])
                self.my.hp = int(msg["your_hp"])
                self.turn = int(msg.get("turn", 0))
                self.my_turn = bool(msg.get("your_turn", False))
                self.status = "Connected. Waiting for your turn."
                self.connected = True

        elif t == "action":
            # Only host processes incoming actions.
            self.host_process_action(msg)

        elif t == "opponent_moved":
            if not self.is_host:
                self.enemy_hp = int(msg["enemy_hp"])
                self.turn = int(msg["turn"])
                self.my_turn = bool(msg["your_turn"])
                self.status = "Opponent moved. Your turn."

        elif t == "move_result":
            if not self.is_host:
                self.enemy_hp = int(msg["enemy_hp"])
                self.turn = int(msg["turn"])
                self.my_turn = bool(msg["your_turn"])
                self.status = "Opponent moved. Your turn."

        elif t == "heal_result":
            if not self.is_host:
                self.my.hp = int(msg["your_hp"])
                self.enemy_hp = int(msg["enemy_hp"])
                self.turn = int(msg["turn"])
                self.my_turn = bool(msg["your_turn"])
                self.status = "Opponent healed. Your turn."
            else:
                # Joiner's heal result is sent back to the host.
                self.enemy_hp = int(msg["your_hp"])
                self.turn = int(msg["turn"])
                self.my_turn = bool(msg["your_turn"])
                self.status = "Opponent healed. Your turn."

        elif t == "attack_result":
            if not self.is_host:
                self.enemy_hp = int(msg["enemy_hp"])
                self.my.hp = int(msg["your_hp"])
                self.turn = int(msg["turn"])
                self.my_turn = bool(msg["your_turn"])

                weapon = WEAPONS[int(msg["weapon"])]
                if msg["hit"]:
                    self.last_result = f"Enemy hit with {weapon['name']} for {msg['damage']}."
                else:
                    self.last_result = f"Enemy fired {weapon['name']} — MISS."
                if msg.get("game_over"):
                    self.game_over = True
                    self.winner = 1
                    self.status = "You lose."
                else:
                    self.status = "Opponent attacked. Your turn."

        elif t == "error":
            self.status = msg.get("message", "Network/game error.")
            self.my_turn = True

        elif t == "turn":
            self.my_turn = bool(msg.get("your_turn", False))

        elif t == "disconnect":
            self.connected = False
            self.status = "Opponent disconnected."

    def poll_network(self):
        if not self.peer:
            return
        for msg in self.peer.poll():
            self.handle_message(msg)
        if not self.peer.running and self.connected and not self.game_over:
            self.connected = False
            self.status = "Opponent disconnected."

    def draw_health(self, surface, x, y, hp, label):
        pygame.draw.rect(surface, (45, 45, 52), (x, y, 360, 28), border_radius=7)
        pygame.draw.rect(surface, (200, 70, 70), (x, y, max(0, int(360 * hp / MAX_HP)), 28), border_radius=7)
        txt = self.font.render(f"{label}: {hp} HP", True, (245, 245, 245))
        surface.blit(txt, (x + 10, y + 2))

    def draw(self, surface, selected_weapon):
        surface.fill((18, 20, 27))

        title = self.title.render("PROXIMITY WARS", True, (240, 240, 250))
        surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 24))

        self.draw_health(surface, 55, 95, self.my.hp, "YOU")
        self.draw_health(surface, WIDTH - 415, 95, self.enemy_hp, "OPPONENT")

        # Board.
        for i in range(BOARD_W):
            x = BOARD_X + i * TILE
            rect = pygame.Rect(x, BOARD_Y, TILE - 2, TILE - 2)

            if i <= 4:
                base = (38, 65, 92)
            else:
                base = (78, 50, 72)
            pygame.draw.rect(surface, base, rect, border_radius=6)

            if i in HEAL_TILES:
                pygame.draw.rect(surface, (75, 170, 110), rect, 4, border_radius=6)
                plus = self.big.render("+", True, (135, 245, 160))
                surface.blit(plus, (x + TILE // 2 - plus.get_width() // 2,
                                     BOARD_Y + TILE // 2 - plus.get_height() // 2))

            n = self.small.render(str(i + 1), True, (190, 195, 205))
            surface.blit(n, (x + 6, BOARD_Y + 6))

        # Region labels.
        a = self.small.render("YOUR REGION", True, (170, 195, 220))
        b = self.small.render("ENEMY REGION", True, (220, 175, 200))
        surface.blit(a, (BOARD_X, BOARD_Y - 25))
        surface.blit(b, (BOARD_X + 5 * TILE, BOARD_Y - 25))

        # Only draw own piece. Enemy position is intentionally hidden.
        cx = BOARD_X + self.my.pos * TILE + TILE // 2
        cy = BOARD_Y + TILE // 2
        pygame.draw.circle(surface, (235, 235, 245), (cx, cy), 23)
        pygame.draw.circle(surface, (30, 30, 38), (cx, cy), 23, 3)
        me = self.big.render("1" if self.my_index == 0 else "2", True, (30, 30, 38))
        surface.blit(me, (cx - me.get_width() // 2, cy - me.get_height() // 2))

        # Status and weapon controls.
        status_color = (120, 230, 150) if self.my_turn else (215, 205, 130)
        status = self.font.render(self.status, True, status_color)
        surface.blit(status, (WIDTH // 2 - status.get_width() // 2, 350))

        hint = self.small.render(
            "A/D or ←/→: move    H: heal    1-4: attack    Esc: quit",
            True, (175, 180, 190)
        )
        surface.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 383))

        panel_y = 425
        for i, w in enumerate(WEAPONS):
            x = 75 + i * 250
            selected = i == selected_weapon
            rect = pygame.Rect(x, panel_y, 220, 120)
            pygame.draw.rect(surface, (42, 44, 54) if not selected else (57, 64, 82), rect, border_radius=10)
            pygame.draw.rect(surface, (115, 125, 150), rect, 2 if selected else 1, border_radius=10)

            name = self.font.render(f"{i+1}. {w['name']}", True, (240, 240, 245))
            line1 = self.small.render(f"Range: {w['range']} tile(s)", True, (205, 210, 220))
            line2 = self.small.render(f"Damage: {w['damage']} HP", True, (205, 210, 220))
            line3 = self.small.render(w["desc"], True, (155, 165, 180))
            surface.blit(name, (x + 14, panel_y + 12))
            surface.blit(line1, (x + 14, panel_y + 48))
            surface.blit(line2, (x + 14, panel_y + 69))
            surface.blit(line3, (x + 14, panel_y + 92))

        if self.last_result:
            r = self.small.render(self.last_result, True, (245, 220, 130))
            surface.blit(r, (WIDTH // 2 - r.get_width() // 2, 565))

        if self.game_over:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 150))
            surface.blit(overlay, (0, 0))
            if self.winner == self.my_index:
                msg = "YOU WIN!"
            else:
                msg = "YOU LOSE"
            big = self.title.render(msg, True, (250, 250, 250))
            surface.blit(big, (WIDTH // 2 - big.get_width() // 2, 285))
            sub = self.font.render("Press Esc to quit.", True, (225, 225, 230))
            surface.blit(sub, (WIDTH // 2 - sub.get_width() // 2, 350))

