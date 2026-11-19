import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from engine import Match
from rules import ConfigError, default_config, validate_config


class Lobby:
    """Authoritative host for exactly two WebSocket clients.

    After connecting, each client sends {"type": "hello", "config": {...} | null}.
    The first valid config received is used for the match; if neither player
    sends one, the default rules are used. The match starts once both players
    have said hello.
    """

    def __init__(self):
        self.lock = asyncio.Lock()
        self.reset()

    def reset(self):
        self.clients: list[WebSocket | None] = [None, None]
        self.hello = [False, False]
        self.config = None
        self.config_owner = None
        self.match: Match | None = None

    @property
    def started(self):
        return self.match is not None

    async def send(self, player: int, message: dict):
        ws = self.clients[player]
        if ws is None:
            return
        try:
            await ws.send_json(message)
        except Exception:
            pass

    async def deliver(self, outbox):
        for player, message in outbox:
            await self.send(player, message)

    async def on_hello(self, player: int, msg: dict) -> bool:
        """Returns False if the connection should be closed."""
        async with self.lock:
            if self.started or self.hello[player]:
                return True

            raw = msg.get("config")
            if raw is not None:
                try:
                    cfg = validate_config(raw)
                except ConfigError as exc:
                    await self.send(player, {"type": "config_error", "errors": exc.errors})
                    return False
                if self.config is None:
                    self.config = cfg
                    self.config_owner = player
                else:
                    await self.send(player, {
                        "type": "info",
                        "message": "The other player already created this match; using their settings.",
                    })

            self.hello[player] = True
            if not all(self.hello) or None in self.clients:
                await self.send(player, {
                    "type": "waiting",
                    "player": player,
                    "message": f"Connected as Player {player + 1}. Waiting for the other player...",
                })
                return True

            cfg = self.config or default_config()
            self.match = Match(cfg)
            for i in range(2):
                await self.send(i, {"type": "match_start", "player": i, "config": cfg})
            await self.deliver(self.match.start())
            print("Match started:", {k: cfg[k] for k in ("max_hp", "cure_ends_turn")},
                  "cure mode", cfg["cure"]["mode"], "attack mode", cfg["attack_mode"]["type"])
            return True

    async def on_action(self, player: int, msg: dict):
        async with self.lock:
            if self.match is None:
                await self.send(player, {"type": "error", "message": "The match has not started."})
                return
            await self.deliver(self.match.handle(player, msg))

    async def on_disconnect(self, player: int, websocket: WebSocket):
        async with self.lock:
            if self.clients[player] is not websocket:
                return
            self.clients[player] = None
            self.hello[player] = False

            if self.started:
                # A disconnect ends the match; the process stays alive for the next pair.
                other = 1 - player
                if self.clients[other] is not None:
                    await self.send(other, {"type": "disconnect", "message": "The other player disconnected."})
                    try:
                        await self.clients[other].close(code=1000)
                    except Exception:
                        pass
                self.reset()
            elif self.config_owner == player:
                self.config = None
                self.config_owner = None


lobby = Lobby()
app = FastAPI(title="Proximity Wars Host")


@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "players": sum(client is not None for client in lobby.clients),
        "game_started": lobby.started,
    })


@app.get("/")
async def root():
    return JSONResponse({"game": "Proximity Wars", "status": "online", "websocket": "/ws"})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    async with lobby.lock:
        if lobby.clients[0] is None and not lobby.started:
            player = 0
        elif lobby.clients[1] is None and not lobby.started:
            player = 1
        else:
            await websocket.send_json({"type": "error", "message": "Game is full."})
            await websocket.close(code=1008)
            return
        lobby.clients[player] = websocket

    print(f"Player {player + 1} connected.")
    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind == "hello":
                if not await lobby.on_hello(player, message):
                    await websocket.close(code=1008)
                    break
            elif kind == "action":
                await lobby.on_action(player, message)
            elif kind == "disconnect":
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"Player {player + 1} connection error: {exc}")
    finally:
        await lobby.on_disconnect(player, websocket)
        print(f"Player {player + 1} disconnected. Server waiting for the next game.")
