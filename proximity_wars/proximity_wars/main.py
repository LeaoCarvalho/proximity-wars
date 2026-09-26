import argparse
import socket
from game import WIDTH, HEIGHT, FPS, Game
from net_peer import NetPeer

import pygame

PORT = 50505

def make_server(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(1)
    return s

def make_client(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(12)
    s.connect((host, port))
    s.settimeout(0.5)
    return s

def connect_game(is_host, host, port):
    if is_host:
        server = make_server(port)
        print(f"Hosting Proximity Wars on 0.0.0.0:{port}")
        print("Give the other player your reachable IP address.")
        print("For internet play, forward TCP port", port, "or use a VPN such as Tailscale.")
        conn, addr = server.accept()
        print("Peer connected from", addr)
        server.close()
        return conn
    else:
        print(f"Connecting to {host}:{port}...")
        return make_client(host, port)


def main():
    parser = argparse.ArgumentParser(description="Proximity Wars - Pygame P2P prototype")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--host", action="store_true", help="Host a game")
    group.add_argument("--join", metavar="IP", help="Join the host at IP")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Proximity Wars")
    clock = pygame.time.Clock()

    game = Game(is_host=args.host)

    try:
        sock = connect_game(args.host, args.join, args.port)
    except OSError as e:
        game.connection_error = str(e)
        game.status = f"Connection failed: {e}"
        sock = None

    if sock:
        game.attach_peer(NetPeer(sock))

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
        try:
            game.send({"type": "disconnect"})
        except Exception:
            pass
        game.peer.close()
    pygame.quit()


if __name__ == "__main__":
    main()
