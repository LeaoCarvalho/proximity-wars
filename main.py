import argparse
import os
import sys

import pygame

from rules import ConfigError, validate_config
from ui import BG, DIM, FPS, HEIGHT, MUTED, WARN, WIDTH, Button, TextField, set_view, text, to_canvas

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


def make_http_url(host, port=DEFAULT_PORT):
    """http(s)://host:port for the server's HTTP endpoints (feedback, metrics)."""
    ws = make_ws_url(host, port)
    base = ws[: -len("/ws")] if ws.endswith("/ws") else ws
    return "https://" + base[len("wss://"):] if base.startswith("wss://") else "http://" + base[len("ws://"):]


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
    COL_W = 330

    def __init__(self, app):
        self.app = app
        self.server = TextField(app.server, w=420, placeholder="127.0.0.1:8000 or https://...")
        self.server.place(WIDTH // 2 - 340, 230)
        self.room = TextField(app.room, w=150, max_len=8, placeholder="any")
        self.room.place(WIDTH // 2 + 190, 230)
        left, right = WIDTH // 2 - self.COL_W - 10, WIDTH // 2 + 10
        w, h = self.COL_W, 44
        self.buttons = [
            Button("Create match (set the rules)", app.show_setup, w=w, h=h, primary=True).place(left, 330),
            Button("Join match", app.join_match, w=w, h=h).place(left, 382),
            Button("Play vs bot", lambda: app.launch("bot"), w=w, h=h).place(left, 434),
            Button("Watch bot vs bot", lambda: app.launch("bot_vs_bot"), w=w, h=h).place(left, 486),
            Button("Hot seat (2 players, 1 screen)", lambda: app.launch("pvp", offline=True),
                   w=w, h=h).place(right, 330),
            Button("Play vs bot", lambda: app.launch("bot", offline=True), w=w, h=h).place(right, 382),
            Button("Watch bot vs bot", lambda: app.launch("bot_vs_bot", offline=True), w=w, h=h).place(right, 434),
            Button("Send feedback", app.show_feedback, w=w, h=h).place(left, 580),
            Button("Quit", app.quit, w=w, h=h).place(right, 580),
        ]

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            TextField.blur()
        for w in [self.server, self.room, *self.buttons]:
            self.update()
            if w.handle(event):
                self.update()
                return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.quit()

    def update(self):
        self.app.server = self.server.value
        self.app.room = self.room.value.strip().upper()

    def draw(self, surface):
        surface.fill(BG)
        text(surface, "PROXIMITY WARS", (WIDTH // 2, 100), 56, bold=True, center=True)
        text(surface, "rules test lab", (WIDTH // 2, 166), 20, MUTED, center=True)
        if self.app.dev:
            text(surface, "DEV MODE", (WIDTH - 20, 14), 18, WARN, bold=True, right=True)
            if not self.app.dev_key:
                text(surface, "no DEV_KEY in .env: online matches can't use new attacks", (WIDTH - 20, 38),
                     14, DIM, right=True)
        text(surface, "Server", (WIDTH // 2 - 340, 208), 16, MUTED)
        text(surface, "Match code (to join a friend)", (WIDTH // 2 + 190, 208), 16, MUTED)
        self.server.draw(surface)
        self.room.draw(surface)
        text(surface, "ONLINE (server)", (WIDTH // 2 - self.COL_W - 10, 300), 17, MUTED, bold=True)
        text(surface, "THIS COMPUTER (no server)", (WIDTH // 2 + 10, 300), 17, MUTED, bold=True)
        for b in self.buttons:
            b.draw(surface)
        text(surface, "Create a match to get a code to share. Join with that code, or leave it empty to join",
             (WIDTH // 2, 650), 16, DIM, center=True)
        text(surface, "any public match that is waiting. Matches use the rules from Create match if you opened it.",
             (WIDTH // 2, 672), 16, DIM, center=True)


class App:
    def __init__(self, server, room="", dev=False, dev_key=None):
        self.dev = dev            # dev mode: may create and edit attacks
        self.dev_key = dev_key if dev else None   # sent to the server so it accepts new attacks
        self.server = server
        self.room = room
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

    def show_feedback(self, match_id=None):
        from feedback_screen import FeedbackScreen
        self.set_screen(FeedbackScreen(self, match_id=match_id))

    def http_url(self):
        return make_http_url(self.server)

    def setup_rules(self):
        """The setup form's rules if it was opened (False if they have errors), else None (defaults)."""
        if self.setup is None:
            return None
        cfg = self.setup.config()
        if cfg is None:
            self.set_screen(self.setup)  # shows the errors
            return False
        return cfg

    def launch(self, mode, offline=False, cfg=None, room=None, private=False):
        """Start a match. mode: "pvp", "bot" (you vs the bot) or "bot_vs_bot" (watch)."""
        from game import GameScreen
        if cfg is None:
            cfg = self.setup_rules()
            if cfg is False:
                return
        ws = None if offline else make_ws_url(self.server)
        self.set_screen(GameScreen(self, ws, cfg, offline=offline, mode=mode, room=room, private=private))

    def start_match(self, cfg, private=False):
        """Create an online match with these rules (the code is shown while waiting).
        A private match can only be joined with its code."""
        self.launch("pvp", cfg=cfg, private=private)

    def join_match(self):
        from game import GameScreen
        self.set_screen(GameScreen(self, make_ws_url(self.server), None, room=self.room or None))

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
    parser.add_argument("--room", default="", help="Match code to join (with --join)")
    parser.add_argument("--public", action="store_true",
                        help="With --config: let anyone join with an empty code (default: code only)")
    parser.add_argument("--offline", action="store_true",
                        help="Play on this computer without a server (uses --config if given)")
    parser.add_argument("--bot", action="store_true", help="Play against the bot")
    parser.add_argument("--bot-vs-bot", action="store_true", help="Watch two bots play")
    parser.add_argument("--dev", action="store_true",
                        help="Dev mode: allows creating and editing attacks (others can only use built-in "
                             "attacks and attacks stored in the database)")
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
        if not args.dev:
            from attack_browser import unknown_attacks
            try:
                unknown = unknown_attacks(cfg["attacks"], make_http_url(server))
            except (OSError, ValueError) as exc:
                print(f"Cannot check the attacks of {args.config} in the database: {exc}")
                sys.exit(1)
            if unknown:
                print(f"{args.config} has attacks that are not in the database: {', '.join(unknown)}")
                print("Only dev mode (--dev) can create attacks.")
                sys.exit(1)

    pygame.init()
    info = pygame.display.Info()
    pygame.display.set_mode(window_size(info.current_w, info.current_h), pygame.RESIZABLE)
    pygame.display.set_caption("Proximity Wars" + (" (dev mode)" if args.dev else ""))
    try:
        pygame.scrap.init()
    except Exception:
        pass
    pygame.key.start_text_input()
    clock = pygame.time.Clock()

    dev_key = None
    if args.dev:
        from db import load_env
        load_env()
        dev_key = os.environ.get("DEV_KEY", "").strip() or None
        if not dev_key:
            print("Dev mode without DEV_KEY in .env: the server will refuse new attacks in online matches.")
    app = App(server, args.room.strip().upper(), dev=args.dev, dev_key=dev_key)
    mode = "bot_vs_bot" if args.bot_vs_bot else "bot" if args.bot else "pvp"
    if args.offline or mode != "pvp":
        app.launch(mode, offline=args.offline, cfg=cfg)
    elif cfg:
        app.start_match(cfg, private=not args.public)
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
