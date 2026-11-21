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
python main.py --host 127.0.0.1 --port 8000   # --port now defaults to 8000
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

The server address can also be edited on the menu screen.

## Rules test lab

The client opens on a menu:

- **Create match** opens the setup form. Whoever creates the match picks the rules. The other player chooses **Join match**. If both players join, the default rules (the original game) are used.
- The setup form can **Copy JSON** and **Paste > form** / **Paste > start** through the clipboard, and **Load** / **Save** a JSON file.
- **Play offline (no server)** on the menu, or **OFFLINE** on the setup form, runs the match on this computer with no server. Both players share the screen: the view follows whoever's turn it is, Tab switches player by hand, and V shows or hides the opponent's wizard.
- **Edit attacks...** opens the attack editor. An attack is a name, a damage value, and the list of distances (1–9 tiles from the caster) it hits, so `[2, 4, 6, 8]` only hits even distances. Attack lists can be saved and loaded as JSON.

Skip the form from the command line:

```bash
python main.py --host 127.0.0.1 --config examples/cure_C_roaming.json
```

```bash
python main.py --host 127.0.0.1 --join
```

```bash
python main.py --offline --config examples/cards_2-2-1.json
```

`examples/` has a ready-made match per mode plus `attacks_sample_bank.json` (15 cards).

### Match JSON

Tiles are numbered 1–10 as on the board: Player 1 owns 1–5 and Player 2 owns 6–10. A tile outside the player's region is reported as an error and the match does not start. Missing keys fall back to defaults, so `{"max_hp": 50}` is a valid config.

```json
{
  "max_hp": 30,
  "start": {"p1": "random", "p2": 6},
  "cure_ends_turn": false,
  "cures_per_turn": 1,
  "cure": {"mode": "A", "points": {"p1": [1, 5], "p2": [6, 10]}, "value": 8, "cooldown": 3},
  "attack_mode": {"type": "default"},
  "attacks": [{"name": "Magic knife", "damage": 20, "tiles": [1], "desc": "Enchanted knife", "tier": "gold"}]
}
```

Each attack can also have a `tier` (`bronze`, `silver` or `gold`, default `bronze`), which picks the card frame `assets/card_<tier>.png`, and an optional `art` file name. Card art is loaded from `assets/art/`: the `art` key if given, otherwise the card name in lower case with underscores (`Magic knife` -> `assets/art/magic_knife.png`). Cards without art just show the empty frame.

Cooldowns count the owner's own turns: `1` means the cure is available again on your next turn, `0` means immediately, and `null` / `"never"` means it never comes back.

| `cure.mode` | Keys | Behaviour |
|---|---|---|
| `A` | `points`, `value`, `cooldown` | Fixed points. Once a player has used all of theirs, they recharge together after the cooldown. |
| `B` | `values` (5 per player, 0 = none) | Every tile has one cure that never comes back. |
| `C` | `options`, `value`, `cooldown` | One point per player. When used it is destroyed and, after the cooldown, reappears on a random option tile. |
| `custom` | `points` (`[{"tile", "value"}]`), `cooldown`, `recharge` (`each` / `all_used`), `respawn` (`same` / `random`), `options` | Each piece can be tested on its own. The default config is a custom mode that matches the original game. |

| `attack_mode.type` | Keys | Behaviour |
|---|---|---|
| `default` | – | Every attack in `attacks` is always available (max 9). |
| `2-2-1` | `hand_size` (2) | `2*hand_size+1` cards are drawn from `attacks`. The used card swaps with the shared waiting card. |
| `roguelike` | `initial_cards` (3), `discards_per_pick` (1), `choices` (3) | Used cards are discarded. Every `discards_per_pick` used cards you pick 1 of `choices` random cards from `attacks`. Picking is free and can be done on either turn. |

### Code layout

- `rules.py`: defaults, sample cards, config validation (shared by client and server)
- `engine.py`: authoritative match rules, independent of networking
- `server.py`: FastAPI WebSocket host around the engine
- `main.py`, `setup_screen.py`, `game.py`, `ui.py`, `sprites.py`: Pygame client (the match screen is drawn at 1920x1080 and scaled to the window, which can be resized)
- `local_peer.py`: offline mode, runs the engine in-process
- `assets/`: sprites, card templates, distance meter and background (client only)

Render needs `rules.py` and `engine.py` next to `server.py`. They have no extra dependencies.

## Render notes

Render provides the public HTTP(S) endpoint. WebSocket clients should use `wss://` over the public internet.

The server process stays alive after a player disconnects and can accept a new pair of players. A third simultaneous client receives `Game is full`.
