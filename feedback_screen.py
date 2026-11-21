"""Feedback form. Sends to the server (POST /feedback); if the server can't be
reached, the feedback is saved in the local metrics folder instead."""

import json
import threading
import urllib.error
import urllib.request

import pygame

from metrics import MetricsStore
from ui import BAD, BG, DIM, GOOD, MUTED, WARN, WIDTH, Button, Cycle, TextArea, TextField, text

RATINGS = [(None, "No rating"), (1, "1 - Bad"), (2, "2 - Meh"), (3, "3 - OK"), (4, "4 - Good"), (5, "5 - Great")]


def send_feedback(http_url, entry, timeout=8):
    """POST the feedback; returns (True, message) or (False, reason)."""
    data = json.dumps(entry).encode("utf-8")
    req = urllib.request.Request(http_url.rstrip("/") + "/feedback", data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300, "sent"
    except urllib.error.HTTPError as exc:
        return False, f"server answered {exc.code}"
    except Exception as exc:
        return False, str(exc) or exc.__class__.__name__


class FeedbackScreen:
    def __init__(self, app, match_id=None):
        self.app = app
        self.match_id = match_id
        self.body = TextArea(w=760, h=260, placeholder="What did you like? What felt wrong or confusing?",
                             max_len=2000).place(WIDTH // 2 - 380, 150)
        self.rating = Cycle(RATINGS, w=220).place(WIDTH // 2 - 380, 450)
        self.send_button = Button("Send", self.send, w=160, h=44, primary=True).place(WIDTH // 2 + 220, 520)
        self.buttons = [Button("Back", app.show_menu, w=160, h=44).place(WIDTH // 2 - 380, 520), self.send_button]
        self.message, self.color = "", MUTED
        self.sending = False
        self.result = None
        TextField.focused = self.body

    def send(self):
        if self.sending:
            return
        if not self.body.value.strip():
            self.message, self.color = "Write something first.", BAD
            return
        entry = {"text": self.body.value.strip(), "rating": self.rating.value,
                 "match_id": self.match_id, "source": "client"}
        url = self.app.http_url()
        self.sending = True
        self.message, self.color = "Sending...", WARN

        def work():
            ok, reason = send_feedback(url, entry)
            if not ok:
                try:
                    MetricsStore().save_feedback({**entry, "source": "client (server unreachable)"})
                    self.result = (False, f"Could not reach the server ({reason}). Saved on this computer "
                                          "in data/feedback.jsonl instead.")
                except OSError as exc:
                    self.result = (False, f"Could not send or save the feedback: {exc}")
            else:
                self.result = (True, "Thank you! Your feedback was sent.")

        threading.Thread(target=work, daemon=True).start()

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            TextField.blur()
        for w in [self.body, self.rating, *self.buttons]:
            if w.handle(event):
                return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.show_menu()

    def update(self):
        if self.result:
            ok, msg = self.result
            self.result = None
            self.sending = False
            self.message, self.color = msg, (GOOD if ok else WARN)
            if ok:
                self.body.value = ""

    def draw(self, surface):
        surface.fill(BG)
        text(surface, "SEND FEEDBACK", (WIDTH // 2, 60), 40, bold=True, center=True)
        note = "about the match you just played" if self.match_id else "about the game"
        text(surface, f"Tell us what you think {note}.", (WIDTH // 2, 110), 18, MUTED, center=True)
        self.body.draw(surface)
        text(surface, "Rating (optional)", (WIDTH // 2 - 380, 424), 16, MUTED)
        self.rating.draw(surface)
        self.send_button.enabled = not self.sending
        for b in self.buttons:
            b.draw(surface)
        text(surface, self.message, (WIDTH // 2, 600), 17, self.color, center=True)
        text(surface, "Enter adds a new line. Esc: back to menu.", (WIDTH // 2, 680), 15, DIM, center=True)
