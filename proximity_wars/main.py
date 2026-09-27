import argparse

import pygame

from game import WIDTH, HEIGHT, FPS, GameClient
from net_peer import NetPeer

PORT = 50505


def make_ws_url(host, port):
    host = host.strip()
    if host.startswith("ws://") or host.startswith("wss://"):
        base = host.rstrip("/")
        return base if base.endswith("/ws") else base + "/ws"

    if host.startswith("http://"):
        return "ws://" + host[len("http://"):].rstrip("/") + "/ws"

    if host.startswith("https://"):
        return "wss://" + host[len("https://"):].rstrip("/") + "/ws"

    scheme = "ws" if host in ("127.0.0.1", "localhost") else "ws"
    return f"{scheme}://{host}:{port}/ws"


def main():
    parser = argparse.ArgumentParser(
        description="Proximity Wars client"
    )
    parser.add_argument(
        "--host",
        required=True,
        help="Host/IP, HTTP(S) URL, or WebSocket URL of the Proximity Wars server"
    )
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Proximity Wars")
    clock = pygame.time.Clock()

    game = GameClient()

    try:
        ws_url = make_ws_url(args.host, args.port)
        print(f"Connecting to {ws_url}...")
        game.attach_peer(NetPeer(ws_url))
    except Exception as exc:
        game.status = f"Connection failed: {exc}"

    selected_weapon = 0
    running = True

    while running:
        clock.tick(FPS)
        game.poll_network()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

                if game.game_over:
                    continue

                if event.key in (pygame.K_LEFT, pygame.K_a):
                    game.local_move(-1)
                elif event.key in (pygame.K_RIGHT, pygame.K_d):
                    game.local_move(1)
                elif event.key == pygame.K_h:
                    game.local_heal()
                elif pygame.K_1 <= event.key <= pygame.K_4:
                    selected_weapon = event.key - pygame.K_1
                    game.local_attack(selected_weapon)

        game.draw(screen, selected_weapon)
        pygame.display.flip()

    if game.peer:
        game.send({"type": "disconnect"})
        game.peer.close()

    pygame.quit()


if __name__ == "__main__":
    main()
