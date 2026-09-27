import pygame
import random as rnd
from dataclasses import dataclass

WIDTH, HEIGHT = 1100, 720
FPS = 60

BOARD_W = 10
TILE = 88
BOARD_X = (WIDTH - BOARD_W * TILE) // 2
BOARD_Y = 235

MAX_HP = 30

HEAL_TILES = {0: 3, 9: 3}

WEAPONS = [
    {"name": "Magic knife", "range": 1, "damage": 20, "desc": "Enchanted knife, a wizard's best friend"},
    {"name": "Magical punch", "range": 2, "damage": 10, "desc": "Ethereal big conjured hand"},
    {"name": "Fireball", "range": 4, "damage": 5, "desc": 'I CAST FIREBALL'},
    {"name": "Magic bolt", "range": 5, "damage": 4, "desc": "A magical ethereal bolt"},
]


@dataclass
class PlayerState:
    pos: int = 0
    hp: int = MAX_HP


class GameClient:
    """Pygame client. Never stores the opponent's exact position."""

    def __init__(self):
        self.player_index = None
        self.my = PlayerState()
        self.enemy_hp = MAX_HP

        self.peer = None
        self.connected = False
        self.game_started = False
        self.my_turn = False
        self.turn = 0

        self.status = "Connecting..."
        self.last_result = ""
        self.game_over = False
        self.winner = None

        self.font = pygame.font.SysFont("arial", 22)
        self.small = pygame.font.SysFont("arial", 16)
        self.big = pygame.font.SysFont("arial", 36, bold=True)
        self.title = pygame.font.SysFont("arial", 48, bold=True)

        self.last_heal_tile = 0

    def attach_peer(self, peer):
        self.peer = peer
        self.connected = True
        self.status = "Connected. Waiting for the host..."

    def send(self, message):
        if self.peer and self.peer.running:
            self.peer.send(message)

    def local_move(self, direction):
        if not self.can_act():
            return

        new_pos = self.my.pos + direction
        if self.player_index == 0:
            legal = 0 <= new_pos <= 4
        else:
            legal = 5 <= new_pos <= 9

        if not legal:
            self.status = "You cannot enter the enemy region."
            return

        self.send({"type": "action", "action": "move", "direction": direction})
        self.my_turn = False
        self.status = "Move sent. Waiting for opponent..."

    def local_heal(self):
        if not self.can_act():
            return

        if self.my.pos not in HEAL_TILES:
            self.status = "You can only heal on the glowing tile."
            return

        if self.my.hp >= MAX_HP:
            self.status = "You are already at full health."
            return
        
        # TODO: Improve
        if self.player_index == 1:
            new_heal_tile = rnd.randint(0, 4)
        else:
            new_heal_tile = rnd.randint(5, 9)
        tmp = HEAL_TILES[self.last_heal_tile]
        HEAL_TILES.pop(self.last_heal_tile)
        HEAL_TILES[new_heal_tile] = tmp
        self.last_heal_tile = new_heal_tile

        self.send({"type": "action", "action": "heal"})
        self.my_turn = False
        self.status = "Heal sent. Waiting for opponent..."

    def local_attack(self, weapon_id):
        if not self.can_act():
            return

        if not 0 <= weapon_id < len(WEAPONS):
            return

        self.send({
            "type": "action",
            "action": "attack",
            "weapon": weapon_id,
        })
        self.my_turn = False
        self.status = f"{WEAPONS[weapon_id]['name']} fired. Waiting for result..."

    def can_act(self):
        if not self.connected:
            self.status = "Not connected to host."
            return False
        if not self.game_started:
            self.status = "Waiting for the second player..."
            return False
        if self.game_over:
            return False
        if not self.my_turn:
            self.status = "It is not your turn."
            return False
        return True

    def handle_message(self, msg):
        t = msg.get("type")

        if t == "waiting":
            self.status = msg.get("message", "Waiting for another player...")

        elif t == "game_start":
            self.player_index = int(msg["player"])
            self.my.pos = int(msg["your_pos"])
            self.my.hp = int(msg["your_hp"])
            self.enemy_hp = int(msg["opponent_hp"])
            self.turn = int(msg["turn"])
            self.my_turn = bool(msg["your_turn"])
            self.game_started = True
            self.status = (
                "Your turn."
                if self.my_turn
                else "Opponent's turn."
            )

        elif t == "action_result":
            self.my.pos = int(msg.get("your_pos", self.my.pos))
            self.my.hp = int(msg["your_hp"])
            self.enemy_hp = int(msg["opponent_hp"])
            self.turn = int(msg["turn"])
            self.my_turn = bool(msg["your_turn"])

            if msg["action"] == "move":
                self.status = "You moved. Waiting for opponent."
            elif msg["action"] == "heal":
                self.status = "You healed. Waiting for opponent."

        elif t == "opponent_action":
            self.enemy_hp = int(msg["opponent_hp"])
            self.turn = int(msg["turn"])
            self.my_turn = bool(msg["your_turn"])

            action = msg["action"]
            if action == "move":
                self.status = "Your turn."
            elif action == "heal":
                self.status = "Your turn."

        elif t == "attack_result":
            self.my.hp = int(msg["your_hp"])
            self.enemy_hp = int(msg["opponent_hp"])
            self.turn = int(msg["turn"])
            self.my_turn = False

            weapon = WEAPONS[int(msg["weapon"])]
            if msg["hit"]:
                self.last_result = (
                    f"{weapon['name']}: HIT for {msg['damage']} damage."
                )
            else:
                self.last_result = f"{weapon['name']}: MISS."

            if msg.get("game_over"):
                self.game_over = True
                self.winner = int(msg["winner"])
                self.status = "YOU WIN!" if self.winner == self.player_index else "YOU LOSE"
            else:
                self.status = "Attack resolved. Waiting for opponent."

        elif t == "defense_result":
            self.my.hp = int(msg["your_hp"])
            self.enemy_hp = int(msg["opponent_hp"])
            self.turn = int(msg["turn"])
            self.my_turn = False

            if msg["hit"]:
                self.last_result = f"You were hit for {msg['damage']} damage."
            else:
                self.last_result = ""

            if msg.get("game_over"):
                self.game_over = True
                self.winner = int(msg["winner"])
                self.status = "YOU WIN!" if self.winner == self.player_index else "YOU LOSE"
            else:
                self.status = "You were attacked. Waiting for your turn."

        elif t == "turn":
            self.my_turn = bool(msg["your_turn"])
            if self.my_turn:
                self.status = "Your turn."

        elif t == "error":
            self.status = msg.get("message", "Invalid action.")
            # Host rejected the action, so it is still our turn.
            self.my_turn = True

        elif t == "disconnect":
            self.connected = False
            self.game_started = False
            if not self.game_over:
                self.status = "Disconnected from host."

    def poll_network(self):
        if not self.peer:
            return

        for msg in self.peer.poll():
            self.handle_message(msg)

        if not self.peer.running and self.connected and not self.game_over:
            self.connected = False
            self.status = "Disconnected from host."

    def draw_health(self, surface, x, y, hp, label):
        pygame.draw.rect(surface, (45, 45, 52), (x, y, 360, 28), border_radius=7)
        pygame.draw.rect(
            surface, (200, 70, 70),
            (x, y, max(0, int(360 * hp / MAX_HP)), 28),
            border_radius=7
        )
        txt = self.font.render(f"{label}: {hp} HP", True, (245, 245, 245))
        surface.blit(txt, (x + 10, y + 2))

    def draw(self, surface, selected_weapon):
        surface.fill((18, 20, 27))

        title = self.title.render("PROXIMITY WARS", True, (240, 240, 250))
        surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 24))

        self.draw_health(surface, 55, 95, self.my.hp, "YOU")
        self.draw_health(surface, WIDTH - 415, 95, self.enemy_hp, "OPPONENT")

        for i in range(BOARD_W):
            x = BOARD_X + i * TILE
            rect = pygame.Rect(x, BOARD_Y, TILE - 2, TILE - 2)

            base = (38, 65, 92) if i <= 4 else (78, 50, 72)
            pygame.draw.rect(surface, base, rect, border_radius=6)

            if i in HEAL_TILES and i == self.last_heal_tile:
                pygame.draw.rect(surface, (75, 170, 110), rect, 4, border_radius=6)
                plus = self.big.render("+", True, (135, 245, 160))
                surface.blit(
                    plus,
                    (x + TILE // 2 - plus.get_width() // 2,
                     BOARD_Y + TILE // 2 - plus.get_height() // 2)
                )

            n = self.small.render(str(i + 1), True, (190, 195, 205))
            surface.blit(n, (x + 6, BOARD_Y + 6))

        a = self.small.render("YOUR REGION", True, (170, 195, 220))
        b = self.small.render("ENEMY REGION", True, (220, 175, 200))
        surface.blit(a, (BOARD_X, BOARD_Y - 25))
        surface.blit(b, (BOARD_X + 5 * TILE, BOARD_Y - 25))

        # Only the local player's piece is rendered.
        if self.player_index is not None:
            cx = BOARD_X + self.my.pos * TILE + TILE // 2
            cy = BOARD_Y + TILE // 2
            pygame.draw.circle(surface, (235, 235, 245), (cx, cy), 23)
            pygame.draw.circle(surface, (30, 30, 38), (cx, cy), 23, 3)

            number = str(self.player_index + 1)
            me = self.big.render(number, True, (30, 30, 38))
            surface.blit(
                me,
                (cx - me.get_width() // 2, cy - me.get_height() // 2)
            )

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
            pygame.draw.rect(
                surface,
                (42, 44, 54) if not selected else (57, 64, 82),
                rect,
                border_radius=10
            )
            pygame.draw.rect(
                surface, (115, 125, 150), rect,
                2 if selected else 1,
                border_radius=10
            )

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

            msg = "YOU WIN!" if self.winner == self.player_index else "YOU LOSE"
            big = self.title.render(msg, True, (250, 250, 250))
            surface.blit(big, (WIDTH // 2 - big.get_width() // 2, 285))

            sub = self.font.render("Press Esc to quit.", True, (225, 225, 230))
            surface.blit(sub, (WIDTH // 2 - sub.get_width() // 2, 350))
