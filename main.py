import argparse
import sys

import pygame

from rules import ConfigError, validate_config
from ui import BG, DIM, FPS, HEIGHT, MUTED, WIDTH, Button, TextField, set_view, text, to_canvas

DEFAULT_PORT = 8000


def make_ws_url(host, port=DEFAULT_PORT):
    host = host.strip()
    if host.startswith("ws://") or host.startswith("wss://"):
        base = host.rstrip("/")
        return base if base.endswith("/ws") else base + "/ws"
    if host.startswith("http://"):
        return "ws://" + host[len("http://"):].rstrip("/") + "/ws"
    if host.startswith("https://"):
        return "wss://" + host[len("https://"):].rstrip("/") + "/ws"
    if ":" in host:
        return f"ws://{host}/ws"
    return f"ws://{host}:{port}/ws"


def window_size(desktop_w, desktop_h):
    """A 16:9 window that fits comfortably on the desktop (the game canvas is 1920x1080)."""
    if not desktop_w or not desktop_h:
        return 1280, 720
    w = min(1920, int(desktop_w * 0.92), int(desktop_h * 0.85 * 16 / 9))
    w = max(w, 960)
    return w, w * 9 // 16


def fit_canvas(canvas_size, window_size_):
    """Scale and offset that letterbox the canvas into the window."""
    cw, ch = canvas_size
    ww, wh = window_size_
    scale = min(ww / cw, wh / ch) or 1.0
    return scale, (ww - round(cw * scale)) // 2, (wh - round(ch * scale)) // 2


def present(window, canvas, scale, ox, oy):
    if scale == 1.0 and ox == 0 and oy == 0:
        window.blit(canvas, (0, 0))
        return
    window.fill((0, 0, 0))
    size = (max(1, round(canvas.get_width() * scale)), max(1, round(canvas.get_height() * scale)))
    window.blit(pygame.transform.smoothscale(canvas, size), (ox, oy))


class MenuScreen:
    def __init__(self, app):
        self.app = app
        self.server = TextField(app.server, w=420, placeholder="127.0.0.1:8000 or https://...")
        self.server.place(WIDTH // 2 - 210, 250)
        cx = WIDTH // 2 - 160
        self.buttons = [
            Button("Create match (set the rules)", app.show_setup, w=320, h=46, primary=True).place(cx, 310),
            Button("Join match", app.join_match, w=320, h=46).place(cx, 366),
            Button("Play offline (no server)", app.start_offline, w=320, h=46).place(cx, 422),
            Button("Quit", app.quit, w=320, h=46).place(cx, 490),
        ]

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            TextField.blur()
        for w in [self.server, *self.buttons]:
            if w.handle(event):
                self.app.server = self.server.value
                return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.quit()

    def update(self):
        self.app.server = self.server.value

    def draw(self, surface):
        surface.fill(BG)
        text(surface, "PROXIMITY WARS", (WIDTH // 2, 120), 56, bold=True, center=True)
        text(surface, "rules test lab", (WIDTH // 2, 186), 20, MUTED, center=True)
        text(surface, "Server", (WIDTH // 2 - 210, 228), 16, MUTED)
        self.server.draw(surface)
        for b in self.buttons:
            b.draw(surface)
        text(surface, "The player who creates the match picks the rules; the other player joins.",
             (WIDTH // 2, 560), 16, DIM, center=True)
        text(surface, "If both players join, the default rules are used.", (WIDTH // 2, 582), 16, DIM, center=True)
        text(surface, "Offline runs the match on this computer; both players share the screen.",
             (WIDTH // 2, 604), 16, DIM, center=True)


class App:
    def __init__(self, server):
        self.server = server
        self.running = True
        self.setup = None
        self.screen = MenuScreen(self)

    def set_screen(self, screen):
        TextField.blur()
        self.screen = screen

    def show_menu(self):
        self.set_screen(MenuScreen(self))

    def show_setup(self, cfg=None):
        from setup_screen import SetupScreen
        if self.setup is None or cfg is not None:
            self.setup = SetupScreen(self, cfg)
        self.set_screen(self.setup)
        return self.setup

    def start_match(self, cfg):
        from game import GameScreen
        self.set_screen(GameScreen(self, make_ws_url(self.server), cfg))

    def join_match(self):
        from game import GameScreen
        self.set_screen(GameScreen(self, make_ws_url(self.server), None))

    def start_offline(self, cfg=None):
        """Play on this computer without a server. Uses the setup form's rules if it was opened."""
        from game import GameScreen
        if cfg is None and self.setup is not None:
            cfg = self.setup.config()
            if cfg is None:  # the form has errors: show them
                self.set_screen(self.setup)
                return
        self.set_screen(GameScreen(self, None, cfg, offline=True))

    def config_rejected(self, errors, cfg):
        setup = self.show_setup(cfg)
        setup.msg.errors(errors, "The server rejected these settings:")

    def quit(self):
        self.running = False


def main():
    parser = argparse.ArgumentParser(description="Proximity Wars client")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host/IP, host:port, HTTP(S) URL, or WebSocket URL of the server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--config", help="Match JSON file: skip the form and create the match right away")
    parser.add_argument("--join", action="store_true", help="Join the match right away")
    parser.add_argument("--offline", action="store_true",
                        help="Play on this computer without a server (uses --config if given)")
    args = parser.parse_args()

    server = args.host
    if "://" not in server and ":" not in server:
        server = f"{server}:{args.port}"

    cfg = None
    if args.config:
        try:
            with open(args.config, encoding="utf-8") as f:
                cfg = validate_config(f.read())
        except (OSError, ConfigError) as exc:
            print(f"Cannot use {args.config}:")
            for line in getattr(exc, "errors", [str(exc)]):
                print("  -", line)
            sys.exit(1)

    pygame.init()
    info = pygame.display.Info()
    pygame.display.set_mode(window_size(info.current_w, info.current_h), pygame.RESIZABLE)
    pygame.display.set_caption("Proximity Wars")
    try:
        pygame.scrap.init()
    except Exception:
        pass
    pygame.key.start_text_input()
    clock = pygame.time.Clock()

    app = App(server)
    if args.offline:
        app.start_offline(cfg)
    elif cfg:
        app.start_match(cfg)
    elif args.join:
        app.join_match()

    canvases = {}
    while app.running:
        clock.tick(FPS)
        window = pygame.display.get_surface()
        size = getattr(app.screen, "size", (WIDTH, HEIGHT))
        if size not in canvases:
            canvases[size] = pygame.Surface(size).convert()
        canvas = canvases[size]
        scale, ox, oy = fit_canvas(size, window.get_size())
        set_view(scale, ox, oy)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                app.running = False
            else:
                if hasattr(event, "pos") and event.type != pygame.VIDEORESIZE:
                    event = pygame.event.Event(event.type, {**event.dict, "pos": to_canvas(event.pos)})
                app.screen.handle(event)
        app.screen.update()
        app.screen.draw(canvas)
        present(window, canvas, scale, ox, oy)
        pygame.display.flip()

    close = getattr(app.screen, "close", None)
    if close:
        close()
    pygame.quit()


if __name__ == "__main__":
    main()
