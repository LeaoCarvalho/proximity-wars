# Proximity Wars — Client / FastAPI Host / Client

The Render deployment is now a dedicated authoritative FastAPI host. Players connect to it through WebSockets.

## Architecture

```text
Pygame Client 1 ── WebSocket ──┐
                               │
                         FastAPI Host
                               │
Pygame Client 2 ── WebSocket ──┘
```

The host owns both hidden positions, health, turn order, attacks, healing, and win conditions. A client receives its own position but never the opponent's exact position.

## Render

Use:

```text
Build Command:
pip install -r requirements-server.txt

Start Command:
uvicorn server:app --host 0.0.0.0 --port $PORT
```

The service exposes:

- `GET /health` — Render health check
- `GET /` — basic status
- `WS /ws` — game connection

Render health checks are ordinary HTTP requests and therefore cannot accidentally consume a player slot.

## Local server

Install server dependencies:

```bash
pip install -r requirements-server.txt
```

Start:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

The host is available at `ws://127.0.0.1:8000/ws`.

## Client

Install client dependencies:

```bash
pip install -r requirements-client.txt
```

Local:

```bash
python main.py --host 127.0.0.1 --port 8000
```

For Render:

```bash
python main.py --host https://YOUR-SERVICE.onrender.com
```

The client automatically converts `https://...` to `wss://.../ws`.

You can also pass a WebSocket URL directly:

```bash
python main.py --host wss://YOUR-SERVICE.onrender.com/ws
```

## Render notes

Render provides the public HTTP(S) endpoint. WebSocket clients should use `wss://` over the public internet.

The server process stays alive after a player disconnects and can accept a new pair of players. A third simultaneous client receives `Game is full`.
