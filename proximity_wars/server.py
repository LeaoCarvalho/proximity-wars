import asyncio
import os
import random
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

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
    """Authoritative game host for exactly two WebSocket clients."""

    def __init__(self):
        self.clients: list[WebSocket | None] = [None, None]
        self.positions: list[int | None] = [None, None]
        self.hp = [MAX_HP, MAX_HP]
        self.turn = 0
        self.game_over = False
        self.winner: int | None = None
        self.started = False
        self.lock = asyncio.Lock()

    async def send(self, player: int, message: dict):
        ws = self.clients[player]
        if ws is None:
            return
        try:
            await ws.send_json(message)
        except Exception:
            pass

    async def broadcast(self, message: dict):
        await asyncio.gather(*(self.send(i, message) for i in range(2)))

    def reset(self):
        self.clients = [None, None]
        self.positions = [None, None]
        self.hp = [MAX_HP, MAX_HP]
        self.turn = 0
        self.game_over = False
        self.winner = None
        self.started = False

    def legal_move(self, player: int, pos: int, direction: int) -> bool:
        new_pos = pos + direction
        return (0 <= new_pos <= 4) if player == 0 else (5 <= new_pos <= 9)

    async def start_game(self):
        self.positions[0] = random.randint(0, 3)
        self.positions[1] = random.randint(6, 9)
        self.turn = 0
        self.started = True

        for player in range(2):
            await self.send(player, {
                "type": "game_start",
                "player": player,
                "your_pos": self.positions[player],
                "your_hp": self.hp[player],
                "opponent_hp": self.hp[1 - player],
                "turn": self.turn,
                "your_turn": player == 0,
            })

        print(
            f"Game started. P1 hidden pos={self.positions[0]}, "
            f"P2 hidden pos={self.positions[1]}"
        )

    async def process_action(self, player: int, msg: dict):
        async with self.lock:
            if not self.started or self.game_over:
                return

            if player != self.turn:
                await self.send(player, {
                    "type": "error",
                    "message": "It is not your turn."
                })
                return

            if msg.get("type") != "action":
                return

            action = msg.get("action")
            if action == "move":
                await self.process_move(player, msg)
            elif action == "heal":
                await self.process_heal(player)
            elif action == "attack":
                await self.process_attack(player, msg)
            else:
                await self.send(player, {
                    "type": "error",
                    "message": "Unknown action."
                })

    def next_turn(self):
        self.turn = 1 - self.turn

    async def process_move(self, player: int, msg: dict):
        try:
            direction = int(msg.get("direction"))
        except (TypeError, ValueError):
            await self.send(player, {"type": "error", "message": "Invalid move."})
            return

        if direction not in (-1, 1):
            await self.send(player, {"type": "error", "message": "Invalid move."})
            return

        old_pos = self.positions[player]
        if old_pos is None or not self.legal_move(player, old_pos, direction):
            await self.send(player, {
                "type": "error",
                "message": "You cannot enter the enemy region."
            })
            return

        new_pos = old_pos + direction
        self.positions[player] = new_pos
        self.next_turn()

        await self.send(player, {
            "type": "action_result",
            "action": "move",
            "your_pos": new_pos,
            "your_hp": self.hp[player],
            "opponent_hp": self.hp[1 - player],
            "turn": self.turn,
            "your_turn": False,
        })

        await self.send(1 - player, {
            "type": "opponent_action",
            "action": "move",
            "opponent_hp": self.hp[player],
            "turn": self.turn,
            "your_turn": True,
        })

    async def process_heal(self, player: int):
        pos = self.positions[player]
        amount = 3#HEAL_TILES.get(pos)

        if not amount:
            await self.send(player, {
                "type": "error",
                "message": "You can only heal on the glowing tile."
            })
            return

        if self.hp[player] >= MAX_HP:
            await self.send(player, {
                "type": "error",
                "message": "You are already at full health."
            })
            return

        self.hp[player] = min(MAX_HP, self.hp[player] + amount)
        self.next_turn()

        await self.send(player, {
            "type": "action_result",
            "action": "heal",
            "your_hp": self.hp[player],
            "opponent_hp": self.hp[1 - player],
            "turn": self.turn,
            "your_turn": False,
        })

        await self.send(1 - player, {
            "type": "opponent_action",
            "action": "heal",
            "opponent_hp": self.hp[player],
            "turn": self.turn,
            "your_turn": True,
        })

    async def process_attack(self, player: int, msg: dict):
        try:
            weapon_id = int(msg.get("weapon"))
        except (TypeError, ValueError):
            await self.send(player, {"type": "error", "message": "Invalid weapon."})
            return

        if not 0 <= weapon_id < len(WEAPONS):
            await self.send(player, {"type": "error", "message": "Invalid weapon."})
            return

        opponent = 1 - player
        distance = abs(self.positions[player] - self.positions[opponent])
        weapon = WEAPONS[weapon_id]
        hit = distance <= weapon["range"]
        damage = weapon["damage"] if hit else 0

        if hit:
            self.hp[opponent] = max(0, self.hp[opponent] - damage)

        self.next_turn()

        if self.hp[opponent] <= 0:
            self.game_over = True
            self.winner = player

        await self.send(player, {
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

        await self.send(opponent, {
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

        if not self.game_over:
            await self.send(self.turn, {"type": "turn", "your_turn": True})
        else:
            print(f"Player {player + 1} won.")

    async def receive_client(self, player: int, websocket: WebSocket):
        try:
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "action":
                    await self.process_action(player, message)
                elif message.get("type") == "disconnect":
                    break
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            print(f"Player {player + 1} connection error: {exc}")
        finally:
            print(f"Player {player + 1} disconnected.")


server = GameServer()


app = FastAPI(title="Proximity Wars Host")


@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "players": sum(client is not None for client in server.clients),
        "game_started": server.started,
    })


@app.get("/")
async def root():
    return JSONResponse({
        "game": "Proximity Wars",
        "status": "online",
        "websocket": "/ws",
    })


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Reserve one of the two player slots. A third connection is rejected.
    async with server.lock:
        if server.clients[0] is None:
            player = 0
        elif server.clients[1] is None:
            player = 1
        else:
            await websocket.send_json({
                "type": "error",
                "message": "Game is full."
            })
            await websocket.close(code=1008)
            return

        server.clients[player] = websocket

    print(f"Player {player + 1} connected via WebSocket.")

    await server.send(player, {
        "type": "waiting",
        "player": player,
        "message": (
            "Connected as Player 1. Waiting for Player 2..."
            if player == 0 else "Connected as Player 2. Starting game..."
        ),
    })

    if server.clients[0] is not None and server.clients[1] is not None and not server.started:
        await server.start_game()

    try:
        await server.receive_client(player, websocket)
    finally:
        async with server.lock:
            if server.clients[player] is websocket:
                server.clients[player] = None

            # A disconnected player ends the current match, but the Render
            # process remains alive and can accept a new pair of players.
            if server.started:
                other = 1 - player
                other_ws = server.clients[other]
                if other_ws is not None:
                    try:
                        await other_ws.send_json({
                            "type": "disconnect",
                            "message": "The other player disconnected."
                        })
                        await other_ws.close(code=1000)
                    except Exception:
                        pass
                    server.clients[other] = None

                server.started = False
                server.game_over = False
                server.winner = None
                server.positions = [None, None]
                server.hp = [MAX_HP, MAX_HP]
                server.turn = 0

        print("Server remains online; waiting for the next game.")
