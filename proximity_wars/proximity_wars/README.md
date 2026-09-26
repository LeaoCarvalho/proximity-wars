# Proximity Wars

A two-player hidden-position strategy game built with Pygame.

## Features

- 1 x W board, default W = 10.
- Player 1 owns tiles 1–5; Player 2 owns tiles 6–10.
- Players cannot enter the opponent's region.
- Opponent position is hidden.
- Both players can always see both health values.
- Three action types:
  - Move one tile left/right.
  - Heal on the special inner-region tile.
  - Fire one of four weapons.
- Misses reveal range information indirectly, encouraging estimation.
- Direct peer-to-peer TCP connection: no central game server.

## Install

```bash
python -m pip install pygame
```

## Run locally on one computer

Open two terminals.

Terminal 1:

```bash
python game.py --host
```

Terminal 2:

```bash
python game.py --join 127.0.0.1
```

## Play over a LAN

On the host computer:

```bash
python game.py --host
```

The host should find its LAN IP, for example `192.168.1.20`, and give it to the other player.

On the joining computer:

```bash
python game.py --join 192.168.1.20
```

Make sure TCP port 50505 is allowed through the host's firewall.

## Play over the internet

The prototype uses a direct TCP connection, so the host must be reachable from the internet.
Usually this means forwarding TCP port 50505 on the host's router to the host PC.

A simpler alternative is to use a mesh VPN such as Tailscale or ZeroTier:
both players join the same private network, then the joiner connects to the host's VPN IP.

Example:

```bash
python game.py --host --port 50505
python game.py --join 100.x.y.z --port 50505
```

## Controls

- Left / A: move left
- Right / D: move right
- H: heal when standing on the green tile
- 1–4: attack
- Esc: quit

## Current playtest values

| Weapon | Range | Damage |
|---|---:|---:|
| Pulse | 1 | 30 |
| Bolt | 2 | 22 |
| Wave | 3 | 16 |
| Snipe | 4 | 12 |

Healing restores 35 HP and is only available on the center-adjacent tile of each player's region.

These values are deliberately stored near the top of `game.py` so they are easy to tune after playtesting.

## Networking architecture

This version is "peer-to-peer" in the practical direct-connection sense:

1. One player hosts a TCP socket.
2. The other player connects directly to that player.
3. Each side keeps its own private position.
4. Actions are sent as commands.
5. The host validates the command against its private copy of both positions.
6. The host sends only information the other player should know:
   - whether an attack hit,
   - damage dealt,
   - public health,
   - whose turn it is,
   - the joiner's own resulting position after their move.
7. The opponent's exact position is never included in network messages.

### Important limitation

The host is still the session authority for validation. This is intentional for a first playable prototype because it prevents easy desynchronization and cheating.

A fully symmetric lockstep P2P implementation is possible, but it requires deterministic state simulation, sequence numbers, acknowledgements, reconnection handling, and stronger anti-cheat rules.

### Internet security note

This prototype uses plain TCP/JSON and is intended for a game prototype, not production deployment. A production release should add authenticated/encrypted transport, reconnect support, protocol versioning, action sequence numbers, and stronger validation.
