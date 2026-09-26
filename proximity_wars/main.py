import argparse
import socket

import pygame

from game import WIDTH, HEIGHT, FPS, GameClient
from net_peer import NetPeer

PORT = 50505


def connect_to_host(host, port):
    print(f"Connecting to host {host}:{port}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(12)
    sock.connect((host, port))
    sock.settimeout(0.5)
    return sock


def main():
    parser = argparse.ArgumentParser(
        description="Proximity Wars client"
    )
    parser.add_argument(
        "--host",
        required=True,
        help="IP address / hostname of the Proximity Wars host"
    )
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Proximity Wars")
    clock = pygame.time.Clock()

    game = GameClient()

    try:
        sock = connect_to_host(args.host, args.port)
        game.attach_peer(NetPeer(sock))
    except OSError as exc:
        game.status = f"Connection failed: {exc}"
        sock = None

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
