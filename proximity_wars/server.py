import argparse
import random
import socket
import threading
import time
import os

from net_peer import NetPeer

PORT = os.getenv("PORT_OF_GAME") or 8000
BOARD_W = 10
MAX_HP = 30

HEAL_TILES = {0: 3, 9: 3}

WEAPONS = [
    {"name": "Magic knife", "range": 1, "damage": 20},
    {"name": "Magical punch", "range": 2, "damage": 10},
    {"name": "Fireball", "range": 4, "damage": 5},
    {"name": "Magic bolt", "range": 5, "damage": 4},
]


class GameServer:
    """Authoritative host for exactly two clients."""

    def __init__(self):
        self.peers = [None, None]
        self.positions = [None, None]
        self.hp = [MAX_HP, MAX_HP]
        self.turn = 0
        self.game_over = False
        self.winner = None
        self.started = False
        self.lock = threading.Lock()

    def send(self, player, message):
        peer = self.peers[player]
        if peer and peer.running:
            peer.send(message)

    def broadcast(self, message):
        for i in range(2):
            self.send(i, message)

    def legal_move(self, player, pos, direction):
        new_pos = pos + direction
        return (0 <= new_pos <= 4) if player == 0 else (5 <= new_pos <= 9)

    def start_game(self):
        # Player 0 lives on the left; player 1 on the right.
        self.positions[0] = random.randint(0, 3)
        self.positions[1] = random.randint(6, 9)
        self.turn = 0
        self.started = True

        # Each player receives ONLY their own position.
        for p in range(2):
            self.send(p, {
                "type": "game_start",
                "player": p,
                "your_pos": self.positions[p],
                "your_hp": self.hp[p],
                "opponent_hp": self.hp[1 - p],
                "turn": self.turn,
                "your_turn": p == 0,
            })

        print(
            f"Game started. P1 hidden pos={self.positions[0]}, "
            f"P2 hidden pos={self.positions[1]}"
        )

    def public_state(self):
        return {
            "hp": self.hp[:],
            "turn": self.turn,
            "game_over": self.game_over,
            "winner": self.winner,
        }

    def process_action(self, player, msg):
        with self.lock:
            if not self.started or self.game_over:
                return

            if player != self.turn:
                self.send(player, {
                    "type": "error",
                    "message": "It is not your turn."
                })
                return

            if msg.get("type") != "action":
                return

            action = msg.get("action")

            if action == "move":
                self.process_move(player, msg)
            elif action == "heal":
                self.process_heal(player)
            elif action == "attack":
                self.process_attack(player, msg)
            else:
                self.send(player, {
                    "type": "error",
                    "message": "Unknown action."
                })

    def next_turn(self):
        self.turn = 1 - self.turn

    def process_move(self, player, msg):
        try:
            direction = int(msg.get("direction"))
        except (TypeError, ValueError):
            return

        if direction not in (-1, 1):
            self.send(player, {"type": "error", "message": "Invalid move."})
            return

        old_pos = self.positions[player]
        new_pos = old_pos + direction

        if not self.legal_move(player, old_pos, direction):
            self.send(player, {
                "type": "error",
                "message": "You cannot enter the enemy region."
            })
            return

        self.positions[player] = new_pos
        self.next_turn()

        # Actor learns their own new position.
        self.send(player, {
            "type": "action_result",
            "action": "move",
            "your_pos": new_pos,
            "your_hp": self.hp[player],
            "opponent_hp": self.hp[1 - player],
            "turn": self.turn,
            "your_turn": False,
        })

        # Opponent learns only that movement happened.
        other = 1 - player
        self.send(other, {
            "type": "opponent_action",
            "action": "move",
            "opponent_hp": self.hp[player],
            "turn": self.turn,
            "your_turn": True,
        })

    def process_heal(self, player):
        amount = HEAL_TILES.get(self.positions[player])

        if not amount:
            self.send(player, {
                "type": "error",
                "message": "You can only heal on the glowing tile."
            })
            return

        if self.hp[player] >= MAX_HP:
            self.send(player, {
                "type": "error",
                "message": "You are already at full health."
            })
            return

        self.hp[player] = min(MAX_HP, self.hp[player] + amount)
        self.next_turn()

        self.send(player, {
            "type": "action_result",
            "action": "heal",
            "your_hp": self.hp[player],
            "opponent_hp": self.hp[1 - player],
            "turn": self.turn,
            "your_turn": False,
        })

        other = 1 - player
        self.send(other, {
            "type": "opponent_action",
            "action": "heal",
            "opponent_hp": self.hp[player],
            "turn": self.turn,
            "your_turn": True,
        })

    def process_attack(self, player, msg):
        try:
            weapon_id = int(msg.get("weapon"))
        except (TypeError, ValueError):
            return

        if not 0 <= weapon_id < len(WEAPONS):
            self.send(player, {"type": "error", "message": "Invalid weapon."})
            return

        weapon = WEAPONS[weapon_id]
        opponent = 1 - player
        distance = abs(self.positions[player] - self.positions[opponent])
        hit = distance <= weapon["range"]
        damage = weapon["damage"] if hit else 0

        if hit:
            self.hp[opponent] = max(0, self.hp[opponent] - damage)

        self.next_turn()

        if self.hp[opponent] <= 0:
            self.game_over = True
            self.winner = player

        # Attacker gets the tactical result. Their opponent's position is
        # never revealed.
        self.send(player, {
            "type": "attack_result",
            "weapon": weapon_id,
            "hit": hit,
            "damage": damage,
            "your_hp": self.hp[player],
            "opponent_hp": self.hp[opponent],
            "turn": self.turn,
            "your_turn": False,
            "game_over": self.game_over,
            "winner": self.winner,
        })

        # Defender gets public health information and learns whether they
        # were hit, but never gets the attacker's position.
        self.send(opponent, {
            "type": "defense_result",
            "weapon": weapon_id,
            "hit": hit,
            "damage": damage,
            "your_hp": self.hp[opponent],
            "opponent_hp": self.hp[player],
            "turn": self.turn,
            "your_turn": False,
            "game_over": self.game_over,
            "winner": self.winner,
        })

        if self.game_over:
            print(f"Player {player + 1} won.")
        else:
            # The new turn belongs to the other player.
            self.send(self.turn, {
                "type": "turn",
                "your_turn": True,
            })

    def attach_client(self, player, peer):
        self.peers[player] = peer

    def client_loop(self, player):
        peer = self.peers[player]
        while peer.running:
            for msg in peer.poll():
                if msg.get("type") == "action":
                    self.process_action(player, msg)
                elif msg.get("type") == "disconnect":
                    peer.close()
                    return
            time.sleep(0.01)

    def run(self, port):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("0.0.0.0", port))
        server_socket.listen(2)

        print(f"Proximity Wars HOST listening on 0.0.0.0:{port}")
        print("Waiting for Player 1...")
        conn1, addr1 = server_socket.accept()
        print("Player 1 connected from", addr1)

        peer1 = NetPeer(conn1)
        self.attach_client(0, peer1)

        self.send(0, {
            "type": "waiting",
            "message": "Connected as Player 1. Waiting for Player 2..."
        })

        print("Waiting for Player 2...")
        conn2, addr2 = server_socket.accept()
        print("Player 2 connected from", addr2)

        peer2 = NetPeer(conn2)
        self.attach_client(1, peer2)

        server_socket.close()

        # Start each client's receiver loop.
        threading.Thread(target=self.client_loop, args=(0,), daemon=True).start()
        threading.Thread(target=self.client_loop, args=(1,), daemon=True).start()

        self.start_game()

        try:
            while True:
                if self.game_over:
                    time.sleep(0.2)
                if not all(peer and peer.running for peer in self.peers):
                    print("A client disconnected.")
                    break
                time.sleep(0.2)
        except KeyboardInterrupt:
            print("\nHost shutting down.")
        finally:
            for peer in self.peers:
                if peer:
                    peer.close()


def main():
    parser = argparse.ArgumentParser(description="Proximity Wars authoritative host")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    GameServer().run(args.port)


if __name__ == "__main__":
    main()
