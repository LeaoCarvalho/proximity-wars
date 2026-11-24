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

- **Create match** opens the setup form. Whoever creates the match picks the rules and gets a 4-letter **match code** to share. The other player types the code in the menu's *Match code* box and chooses **Join match**. If nobody set the rules, the default rules (the original game) are used.
- A created match is **Private** (only joinable with its code) or **Public** (the code works, and so does **Join match** with an empty code box), set by *Visibility* in the setup form. Private is the default. With the code box empty, **Join match** joins the oldest public match that is waiting, or opens a public one and waits.
- **Play vs bot** and **Watch bot vs bot** exist both online (the match runs on the server, so it is counted in the server's metrics) and on this computer. The bot picks a random legal action every time. While watching, S speeds the bots up.
- The setup form can **Copy JSON** and **Paste > form** / **Paste > start** through the clipboard, and **Load** / **Save** a JSON file.
- **Hot seat** runs a 2-player match on this computer with no server. Both players share the screen: the view follows whoever's turn it is, Tab switches player by hand, and V shows or hides the opponent's wizard.
- In the setup form, **Opponent** (another player / the bot / bot vs bot) and **Play on** (online server / this computer) choose what START MATCH does. The menu's bot and hot-seat buttons also use the setup form's rules once you have opened it.
- **Send feedback** (menu, or the button at the end of a match) sends a message and an optional 1-5 rating to the server. If the server can't be reached it is saved in `data/feedback.jsonl` on this computer.
- **Edit attacks...** opens the attack editor. An attack is a name, a damage value, and the list of distances (1–9 tiles from the caster) it hits, so `[2, 4, 6, 8]` only hits even distances. Attack lists can be saved and loaded as JSON.

Skip the form from the command line:

```bash
python main.py --host 127.0.0.1 --config examples/cure_C_roaming.json
```

```bash
python main.py --host 127.0.0.1 --join --room ABCD
```

```bash
python main.py --offline --config examples/cards_2-2-1.json
```

```bash
python main.py --bot
```

```bash
python main.py --offline --bot-vs-bot --config examples/cards_roguelike.json
```

`--config` creates a private match (its code is shown while waiting); add `--public` to let `--join` without `--room` find it. `--bot` and `--bot-vs-bot` run on the server unless `--offline` is given.

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
- `server.py`: FastAPI WebSocket host: many 1v1 rooms at once, match codes, bot seats, metrics and feedback endpoints
- `session.py`: one match plus its bots and metrics recording (used by the server and offline)
- `bot.py`: the random bot
- `metrics.py`: match records, feedback, and the summary numbers
- `main.py`, `setup_screen.py`, `game.py`, `ui.py`, `sprites.py`: Pygame client (the match screen is drawn at 1920x1080 and scaled to the window, which can be resized)
- `local_peer.py`: offline mode (hot seat, vs bot, bot vs bot), runs the match in-process
- `feedback_screen.py`: the feedback form
- `assets/`: sprites, card templates, distance meter and background (client only)

- `db.py`: Turso database access (HTTP API), the `.env` loader, and `python db.py create`
- `schema.sql`: the database tables
- `attack_browser.py`: the attack editor's "Add from database" screen

Render needs `rules.py`, `engine.py`, `session.py`, `bot.py`, `metrics.py` and `db.py` next to `server.py`. They have no extra dependencies.

## Metrics

Every match is saved when it ends (finished, or someone left), and every feedback message when it's sent: in the Turso database when one is configured (see "Database" below), otherwise as lines in `matches.jsonl` and `feedback.jsonl`. The server writes to `data/` next to `server.py` (set `METRICS_DIR` to change it). Offline matches are saved in `data/` on the player's computer, marked `"mode": "offline"`.

Each match record has: start/end time and **duration**, who played (human/bot), the rules, the **result** (`finished`, `disconnected` with which players left, or `stopped` for a bot match closed early), the winner, **actions per player** (moves, cures, attacks, card picks, rejected actions) and the full **action log** (time, player, action, card, events, HP after).

Read them from the server:

| URL | What |
|---|---|
| `GET /metrics` | Summary: matches finished / with a disconnect (one or both players), average duration, actions per player, wins by Player 1 and Player 2, per attack stats (see below), how often the bot won (vs humans and in total), cures used (total, by winners, by losers), feedback count and average rating |
| `GET /metrics/matches?limit=50` | The latest match records with action logs (`&log=false` leaves the logs out) |
| `GET /metrics/feedback` | The latest feedback |
| `POST /feedback` | `{"text": "...", "rating": 1-5, "match_id": "..."}` |
| `POST /attacks` | Dev mode: `{"attacks": [...]}` with the `X-Dev-Key: <DEV_KEY>` header stores attacks without playing them |
| `GET /attacks` | Every different attack played (definition, number of matches, last played); used by the attack editor |

Per attack, the summary's `attacks` list has: `matches` (matches it was in play), `uses` (times cast, by either player), `first` (times it was the first attack of a match), `last` (the last attack of a match) and `finishing` (the last attack of a finished match, i.e. the winning blow). Attacks count as different when any field differs. `wins` has `player_1`, `player_2` and `player_1_rate` over finished matches. In SQL, per attack:

```sql
SELECT a.name, SUM(m.uses) AS uses, SUM(m.is_first) AS first, SUM(m.is_last) AS last
FROM MatchAttack m JOIN Attack a ON a.id = m.attack_id GROUP BY a.id ORDER BY uses DESC;
```

Set the `METRICS_TOKEN` environment variable to require `?token=...` on the `/metrics` URLs. For a local folder, `python metrics.py data` prints the same summary.

On Render's free plan the disk is wiped on every deploy or restart, so the files are lost then. Add a persistent disk and point `METRICS_DIR` at it to keep them.

### Database (Turso)

With a Turso database configured, the server stores everything there instead of in files:

| Table | One row per | What |
|---|---|---|
| `MatchLog` | match | mode, who played, start/end/duration, result, winner, who disconnected, actions per player (moves, cures, attacks, picks, rejected, total), the rules |
| `MatchAction` | action | the action log: order, time, player, human/bot, action, card, HP after, events, error |
| `Attack` | different attack | name, damage, hit distances, description, tier, art. Each attack is stored once: its id is a fingerprint of the definition, so editing any field makes a new attack |
| `MatchAttack` | attack in a match | which attacks each match was played with, in list order, with `uses` (times cast), `is_first` / `is_last` (the match's first / last attack cast) |
| `FeedbackLog` | feedback message | text, rating, match, source |

The tables are in [`schema.sql`](schema.sql). Players are numbered 1 and 2 in the database.

1. Copy `.env.example` to `.env` next to `server.py` and fill in `TURSO_DATABASE_URL` (the `libsql://...turso.io` URL from the Turso dashboard) and `TURSO_AUTH_TOKEN` (a read & write token). `.env` is in `.gitignore`, so the token is never committed.
2. Create the tables once: `python db.py create` (or paste `schema.sql` into the Turso SQL console). Run it again after updating the game: it adds new tables and columns (filling the new columns in for older matches) and leaves your data alone.
3. On Render, add the same two variables under the service's Environment settings; they take priority over a `.env` file.

`GET /metrics`, `/metrics/matches` and `/metrics/feedback` (and `python metrics.py`) then read from the database. `GET /attacks` lists every different attack played, with how many matches used it.

**Dev mode:** only a client started with `--dev` (`python main.py --dev`) can create or edit attacks: New, Duplicate, changing a card's fields, and pasting or loading attack files. Without it, the attack screen is read-only and you can only pick from the built-in attacks (Classic 4, Sample bank) and attacks stored in the database. A pasted or loaded match JSON (or `--config`) with attacks that are not in the database is refused. Everyone can load attacks from the database.

The server enforces it too. Set `DEV_KEY` (any long random text, e.g. from `python -c "import secrets; print(secrets.token_urlsafe(32))"`) in the server's `.env` or Render's Environment settings, and the same value in the `.env` of each dev computer. Then the server refuses a match whose attacks are not built in and not in the database (`Attack` table) unless the client was started with `--dev` and has that key; the player is sent back to the setup screen with the reason. Once a dev has played a match with a new attack, it is in the database and everyone can use it. If the database can't be reached, matches with non-built-in attacks are refused (built-in ones still work). Without `DEV_KEY` on the server, it accepts any valid attacks (and says so in its log when it starts). Offline matches never reach the server, so only the client-side check applies to them.

**Saving attacks to the database (dev mode):** the attack editor has **Save this to DB** (the selected attack) and **Save all to DB** (the whole list), so attacks can be stored before anyone plays them. A dev computer whose `.env` has the database writes to it directly; otherwise the game sends them to the server (`POST /attacks` with the `X-Dev-Key` header), which only accepts them with the right `DEV_KEY`. Saved attacks show up in everyone's **Add from database...** list right away ("Saved, not played yet"). To store the built-in attacks (Classic 4 and the sample bank), run `python metrics.py save-builtin-attacks`.

**Loading stored attacks in the game:** in Create match > Edit attacks... (Choose attacks... without dev mode), click **Add from database...**. It lists every attack that was played (most recently played first), with a search box and a card preview. Click attacks to select them, then **Add selected** (attacks already in your list are skipped) or **Replace list with selected**. The list comes from the database in `.env` if your computer has one, otherwise from the server in the menu's Server box. A match is saved in one transaction (all of it or nothing), in the background so the game never waits for the database.

Without `TURSO_DATABASE_URL` everything stays in local files as before. If the database can't be reached, the match or feedback is saved in the local `.jsonl` file instead and an error is printed in the server log (those records are not copied to the database later). Only the server talks to the database: players' computers never need the token, and their offline matches stay in their own `data/` folder.

## Render notes

Render provides the public HTTP(S) endpoint. WebSocket clients should use `wss://` over the public internet.

One server runs any number of matches at the same time; each pair of players gets its own room. When a player disconnects mid-match, the other player is told and that room closes; other matches are not affected. `GET /health` shows how many rooms are open.
