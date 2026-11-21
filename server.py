"""Proximity Wars host: many independent 1v1 matches ("rooms") on one server.

WebSocket protocol (/ws). After connecting, a client sends one hello:

    {"type": "hello", "mode": "pvp" | "bot" | "bot_vs_bot",
     "config": {...} | null, "room": "ABCD" | null, "private": bool}

- pvp with a room code joins that waiting match (public or private).
- pvp without a code joins the oldest *public* match that is waiting for a
  player, or opens a new one (the client is told its code to share). If a
  config is sent and the match has none yet, it is used; otherwise the
  default rules apply.
- pvp with "private": true always opens a new match that can only be joined
  with its code.
- bot: the client plays Player 1 against a random bot. Starts at once.
- bot_vs_bot: two bots play while the client watches. Starts at once.

Then the client sends {"type": "action", ...} messages (see engine.py), and
{"type": "speed", "fast": bool} to speed up bots. Each finished or abandoned
match is written to the metrics store (metrics.py).
"""

import asyncio
import os
import random

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from metrics import MetricsStore
from rules import ConfigError, default_config, validate_config
from session import BOT_DELAY, BOT_DELAY_FAST, MatchSession

MODES = ("pvp", "bot", "bot_vs_bot")
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"   # no I / O, easy to read out loud
BOT = "bot"
SPECTATOR = "spectator"
METRICS_TOKEN = os.environ.get("METRICS_TOKEN")

store = MetricsStore()


async def send(ws, message) -> bool:
    try:
        await ws.send_json(message)
        return True
    except Exception:
        return False


class Room:
    def __init__(self, code, mode, config=None, private=False):
        self.code = code
        self.mode = mode
        self.config = config
        self.private = private             # only joinable with the code
        self.seats = [None, None]          # WebSocket, BOT or None
        self.spectators = []
        self.session: MatchSession | None = None
        self.lock = asyncio.Lock()
        self.bot_task = None
        self.fast = False

    def free_seat(self):
        return next((i for i, s in enumerate(self.seats) if s is None), None)

    def humans(self):
        return [(i, s) for i, s in enumerate(self.seats) if s is not None and s != BOT]

    @property
    def waiting(self):
        return self.session is None and self.mode == "pvp" and self.free_seat() is not None

    async def deliver(self, outbox, actor=None):
        for player, message in outbox:
            seat = self.seats[player]
            if seat is not None and seat != BOT:
                await send(seat, message)
        if self.spectators and any(m.get("type") == "state" for _, m in outbox):
            events = next((m.get("events", []) for p, m in outbox
                           if m.get("type") == "state" and (actor is None or p == actor)), [])
            if actor is not None:
                events = [f"Bot {actor + 1}: {e}" for e in events]
            view = self.session.spectator_view(events)
            for ws in list(self.spectators):
                await send(ws, view)


class Lobby:
    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.where: dict[WebSocket, tuple[Room, object]] = {}
        self.lock = asyncio.Lock()

    def new_code(self):
        while True:
            code = "".join(random.choice(CODE_LETTERS) for _ in range(4))
            if code not in self.rooms:
                return code

    def open_room(self, mode, config=None, private=False):
        room = Room(self.new_code(), mode, config, private)
        self.rooms[room.code] = room
        return room

    # ------------------------------------------------------------------
    async def hello(self, ws, msg) -> bool:
        """Returns False if the connection should be closed."""
        mode = msg.get("mode") or "pvp"
        if mode not in MODES:
            await send(ws, {"type": "error", "message": f"Unknown mode {mode!r}."})
            return False
        cfg = None
        if msg.get("config") is not None:
            try:
                cfg = validate_config(msg["config"])
            except ConfigError as exc:
                await send(ws, {"type": "config_error", "errors": exc.errors})
                return False
        code = str(msg.get("room") or "").strip().upper()
        private = bool(msg.get("private"))

        async with self.lock:
            if ws in self.where:
                return True
            if mode == "bot":
                room = self.open_room(mode, cfg)
                room.seats = [ws, BOT]
                self.where[ws] = (room, 0)
                await self.start(room)
                return True
            if mode == "bot_vs_bot":
                room = self.open_room(mode, cfg)
                room.seats = [BOT, BOT]
                room.spectators.append(ws)
                self.where[ws] = (room, SPECTATOR)
                await self.start(room)
                return True

            if code:
                room = self.rooms.get(code)
                if room is None or not room.waiting:
                    await send(ws, {"type": "error", "message": f"There is no open match with code {code}."})
                    return False
            elif private:
                room = self.open_room(mode, private=True)
            else:
                waiting = [r for r in self.rooms.values()
                           if r.waiting and not r.private and (cfg is None or r.config is None)]
                room = waiting[0] if waiting else self.open_room(mode)

            if cfg is not None:
                if room.config is None:
                    room.config = cfg
                else:
                    await send(ws, {"type": "info", "message":
                                    "The other player already set the rules for this match; using theirs."})
            seat = room.free_seat()
            room.seats[seat] = ws
            self.where[ws] = (room, seat)
            if room.free_seat() is None:
                await self.start(room)
            else:
                kind = "Private match" if room.private else "Match"
                await send(ws, {"type": "waiting", "player": seat, "room": room.code, "private": room.private,
                                "message": f"{kind} code {room.code}. Waiting for the other player..."})
            print(f"Room {room.code}: player {seat + 1} joined ({len(self.rooms)} room(s) open).")
            return True

    async def start(self, room):
        cfg = room.config or default_config()
        kinds = [BOT if s == BOT else "human" for s in room.seats]
        room.session = MatchSession(cfg, kinds, mode="online", room=room.code, store=store)
        base = {"type": "match_start", "config": cfg, "room": room.code, "match_id": room.session.id,
                "players": kinds}
        for i, seat in room.humans():
            await send(seat, {**base, "player": i, "spectator": False})
        for ws in room.spectators:
            await send(ws, {**base, "player": 0, "spectator": True})
        await room.deliver(room.session.start())
        if room.session.bots:
            room.bot_task = asyncio.create_task(self.run_bots(room))
        print(f"Room {room.code}: {room.mode} match started ({cfg['cure']['mode']} cures, "
              f"{cfg['attack_mode']['type']} cards).")

    async def run_bots(self, room):
        try:
            while True:
                await asyncio.sleep(BOT_DELAY_FAST if room.fast else BOT_DELAY)
                async with room.lock:
                    session = room.session
                    if session is None or session.closed:
                        return
                    actor, outbox = session.bot_step()
                    if outbox:
                        await room.deliver(outbox, actor)
        except asyncio.CancelledError:
            pass

    async def action(self, ws, msg):
        room, seat = self.where.get(ws, (None, None))
        if room is None or room.session is None or seat == SPECTATOR:
            await send(ws, {"type": "error", "message": "The match has not started."})
            return
        async with room.lock:
            await room.deliver(room.session.act(seat, msg), seat)

    async def speed(self, ws, msg):
        room, _ = self.where.get(ws, (None, None))
        if room is not None:
            room.fast = bool(msg.get("fast"))

    async def leave(self, ws):
        async with self.lock:
            room, seat = self.where.pop(ws, (None, None))
            if room is None:
                return
            async with room.lock:
                if seat == SPECTATOR:
                    room.spectators.remove(ws)
                else:
                    room.seats[seat] = None
                session = room.session
                if session is not None and not session.closed:
                    if seat == SPECTATOR:
                        if not room.spectators:
                            session.abort(result="stopped")
                    else:
                        gone = [seat]
                        for i, other in room.humans():
                            ok = await send(other, {"type": "disconnect",
                                                    "message": "The other player disconnected."})
                            if not ok:
                                gone.append(i)
                            try:
                                await other.close(code=1000)
                            except Exception:
                                pass
                            # the match is over for them too: free their seat now
                            room.seats[i] = None
                            self.where.pop(other, None)
                        session.abort(disconnected=gone)
                if not room.humans() and not room.spectators:
                    if room.bot_task:
                        room.bot_task.cancel()
                    self.rooms.pop(room.code, None)
            print(f"Room {room.code}: a client left ({len(self.rooms)} room(s) open).")


lobby = Lobby()
app = FastAPI(title="Proximity Wars Host")


def check_token(request: Request):
    if METRICS_TOKEN and request.query_params.get("token") != METRICS_TOKEN:
        raise HTTPException(status_code=403, detail="Add ?token=... to read metrics.")


@app.get("/health")
async def health():
    rooms = list(lobby.rooms.values())
    return JSONResponse({
        "status": "ok",
        "rooms": len(rooms),
        "matches_running": sum(1 for r in rooms if r.session and not r.session.closed),
        "waiting_for_player": sum(1 for r in rooms if r.waiting),
        "waiting_public": sum(1 for r in rooms if r.waiting and not r.private),
        "clients": len(lobby.where),
    })


@app.get("/")
async def root():
    return JSONResponse({"game": "Proximity Wars", "status": "online", "websocket": "/ws",
                         "metrics": "/metrics", "feedback": "POST /feedback"})


@app.get("/metrics")
async def metrics_summary(request: Request):
    check_token(request)
    return JSONResponse(store.summary())


@app.get("/metrics/matches")
async def metrics_matches(request: Request, limit: int = 50, log: bool = True):
    check_token(request)
    records = store.matches(max(1, min(limit, 1000)))
    if not log:
        records = [{k: v for k, v in r.items() if k != "log"} for r in records]
    return JSONResponse(records)


@app.get("/metrics/feedback")
async def metrics_feedback(request: Request, limit: int = 100):
    check_token(request)
    return JSONResponse(store.feedback(max(1, min(limit, 1000))))


@app.post("/feedback")
async def post_feedback(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Send JSON: {\"text\": ..., \"rating\": 1-5}")
    if not isinstance(body, dict) or not str(body.get("text", "")).strip():
        raise HTTPException(status_code=400, detail="The feedback text is empty.")
    record = store.save_feedback(body)
    return JSONResponse({"ok": True, "id": record["id"]})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind == "hello":
                if not await lobby.hello(websocket, message):
                    await websocket.close(code=1008)
                    break
            elif kind == "action":
                await lobby.action(websocket, message)
            elif kind == "speed":
                await lobby.speed(websocket, message)
            elif kind == "disconnect":
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"Connection error: {exc}")
    finally:
        await lobby.leave(websocket)
