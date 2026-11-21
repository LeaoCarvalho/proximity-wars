"""Small Pygame widget toolkit used by the menu, setup form and attack editor."""

import subprocess
import sys

import pygame

from webglue import IS_WEB

WIDTH, HEIGHT = 1100, 720
FPS = 60

BG = (18, 20, 27)
PANEL = (32, 35, 45)
PANEL_HI = (52, 58, 76)
BORDER = (95, 105, 130)
TEXT = (238, 240, 246)
MUTED = (160, 166, 180)
DIM = (110, 115, 128)
ACCENT = (120, 200, 255)
GOOD = (120, 230, 150)
WARN = (240, 205, 120)
BAD = (240, 110, 110)
P1_COLOR = (38, 65, 92)
P2_COLOR = (78, 50, 72)
CURE = (75, 170, 110)

_fonts = {}


# The app draws each screen on a fixed-size canvas and scales it into the
# window; this maps window pixels back to canvas pixels.
_view = [1.0, 0, 0]


def set_view(scale, ox, oy):
    _view[:] = [scale, ox, oy]


def to_canvas(pos):
    scale, ox, oy = _view
    return (int((pos[0] - ox) / scale), int((pos[1] - oy) / scale))


def mouse_pos():
    return to_canvas(pygame.mouse.get_pos())


def font(size=20, bold=False):
    key = (size, bold)
    if key not in _fonts:
        _fonts[key] = pygame.font.SysFont("arial", size, bold=bold)
    return _fonts[key]


def text(surface, s, pos, size=20, color=TEXT, bold=False, center=False, right=False):
    img = font(size, bold).render(str(s), True, color)
    x, y = pos
    if center:
        x -= img.get_width() // 2
    elif right:
        x -= img.get_width()
    surface.blit(img, (x, y))
    return img.get_width()


def fit_text(s, size, max_width, bold=False):
    f = font(size, bold)
    s = str(s)
    if f.size(s)[0] <= max_width:
        return s
    while s and f.size(s + "...")[0] > max_width:
        s = s[:-1]
    return s + "..."


def wrap_text(s, size, max_width):
    f = font(size)
    lines, line = [], ""
    for word in str(s).split():
        candidate = f"{line} {word}".strip()
        if f.size(candidate)[0] <= max_width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


# ----------------------------------------------------------------------
# Clipboard
# ----------------------------------------------------------------------
def copy_to_clipboard(s):
    if IS_WEB:
        from webglue import copy_text
        return copy_text(s)
    try:
        if hasattr(pygame.scrap, "put_text"):
            pygame.scrap.put_text(s)
            return True
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            subprocess.run(["clip"], input=s.encode("utf-16-le"), check=True)
            return True
        except Exception:
            pass
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(s)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False


def paste_from_clipboard():
    if IS_WEB:  # Python can't read the browser clipboard: ask the player to paste into a prompt
        from webglue import ask_text
        return ask_text("Paste here:", "") or ""
    try:
        if hasattr(pygame.scrap, "get_text"):
            value = pygame.scrap.get_text()
            if value:
                return value
    except Exception:
        pass
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        value = root.clipboard_get()
        root.destroy()
        return value
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                                 capture_output=True, check=True)
            return out.stdout.decode(errors="replace")
        except Exception:
            pass
    return ""


# ----------------------------------------------------------------------
# Widgets
# ----------------------------------------------------------------------
class Widget:
    def __init__(self, w, h):
        self.rect = pygame.Rect(0, 0, w, h)

    def place(self, x, y):
        self.rect.topleft = (x, y)
        return self

    def handle(self, event):
        return False

    def draw(self, surface):
        pass


class Button(Widget):
    def __init__(self, label, on_click, w=None, h=36, primary=False, size=18):
        self.label = label
        self.on_click = on_click
        self.primary = primary
        self.size = size
        self.enabled = True
        super().__init__(w or font(size).size(label)[0] + 28, h)

    def handle(self, event):
        if (self.enabled and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.rect.collidepoint(event.pos)):
            self.on_click()
            return True
        return False

    def draw(self, surface):
        hover = self.enabled and self.rect.collidepoint(mouse_pos())
        if self.primary:
            color = (60, 140, 90) if not hover else (75, 170, 110)
        else:
            color = PANEL_HI if hover else PANEL
        if not self.enabled:
            color = (30, 32, 40)
        pygame.draw.rect(surface, color, self.rect, border_radius=8)
        pygame.draw.rect(surface, BORDER, self.rect, 1, border_radius=8)
        text(surface, self.label, (self.rect.centerx, self.rect.y + (self.rect.h - font(self.size).get_height()) // 2),
             self.size, TEXT if self.enabled else DIM, center=True)


class TextField(Widget):
    focused = None

    def __init__(self, value="", w=160, h=34, placeholder="", max_len=200, size=18, label=""):
        super().__init__(w, h)
        self.value = str(value)
        self.placeholder = placeholder
        self.label = label          # shown in the browser's text prompt
        self.max_len = max_len
        self.size = size
        self.invalid = False

    @classmethod
    def blur(cls):
        cls.focused = None

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                if IS_WEB:
                    # a native prompt brings up the phone's keyboard; there is no typing into the canvas
                    from webglue import ask_text
                    answer = ask_text(self.label or self.placeholder or "Enter a value:", self.value)
                    if answer is not None:
                        self.value = answer[: self.max_len]
                    return True
                TextField.focused = self
                return True
            return False
        if TextField.focused is not self:
            return False
        if event.type == pygame.TEXTINPUT:
            self.value = (self.value + event.text)[: self.max_len]
            return True
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                if event.mod & pygame.KMOD_CTRL:
                    self.value = ""
                else:
                    self.value = self.value[:-1]
                return True
            if event.key == pygame.K_v and event.mod & pygame.KMOD_CTRL:
                pasted = paste_from_clipboard().replace("\r", "").replace("\n", " ")
                self.value = (self.value + pasted)[: self.max_len]
                return True
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, pygame.K_TAB):
                TextField.focused = None
                return True
            return True  # swallow other keys while typing
        return False

    def draw(self, surface):
        focused = TextField.focused is self
        pygame.draw.rect(surface, (24, 26, 34), self.rect, border_radius=6)
        border = BAD if self.invalid else (ACCENT if focused else BORDER)
        pygame.draw.rect(surface, border, self.rect, 2 if focused or self.invalid else 1, border_radius=6)
        f = font(self.size)
        shown = self.value if self.value else self.placeholder
        color = TEXT if self.value else DIM
        img = f.render(shown, True, color)
        clip = surface.get_clip()
        inner = self.rect.inflate(-12, -4)
        surface.set_clip(inner.clip(clip) if clip else inner)
        x = inner.x
        if focused and img.get_width() > inner.w:
            x = inner.right - img.get_width() - 4
        surface.blit(img, (x, self.rect.y + (self.rect.h - img.get_height()) // 2))
        if focused and pygame.time.get_ticks() // 500 % 2 == 0:
            cx = min(x + (f.size(self.value)[0] if self.value else 0) + 1, inner.right - 1)
            pygame.draw.line(surface, TEXT, (cx, self.rect.y + 7), (cx, self.rect.bottom - 7), 2)
        surface.set_clip(clip)


NEWLINE, CARRIAGE_RETURN = chr(10), chr(13)


class TextArea(TextField):
    """Multi-line text box: Enter adds a new line, Esc / Tab leave it."""

    def __init__(self, value="", w=600, h=220, placeholder="", max_len=2000, size=18, label=""):
        super().__init__(value, w, h, placeholder, max_len, size, label)

    def handle(self, event):
        if TextField.focused is self and event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.value = (self.value + NEWLINE)[: self.max_len]
                return True
            if event.key == pygame.K_v and event.mod & pygame.KMOD_CTRL:
                self.value = (self.value + paste_from_clipboard().replace(CARRIAGE_RETURN, ""))[: self.max_len]
                return True
        return super().handle(event)

    def lines(self, width):
        out = []
        for para in self.value.split(NEWLINE):
            wrapped = wrap_text(para, self.size, width) if para.strip() else [""]
            out.extend(wrapped)
        return out

    def draw(self, surface):
        focused = TextField.focused is self
        pygame.draw.rect(surface, (24, 26, 34), self.rect, border_radius=6)
        border = BAD if self.invalid else (ACCENT if focused else BORDER)
        pygame.draw.rect(surface, border, self.rect, 2 if focused else 1, border_radius=6)
        inner = self.rect.inflate(-16, -12)
        line_h = font(self.size).get_linesize()
        if not self.value:
            text(surface, self.placeholder, inner.topleft, self.size, DIM)
            lines = [""]
        else:
            lines = self.lines(inner.w)
            visible = max(1, inner.h // line_h)
            lines = lines[-visible:]          # keep the end (where you type) in view
            for i, line in enumerate(lines):
                text(surface, line, (inner.x, inner.y + i * line_h), self.size)
        if focused and pygame.time.get_ticks() // 500 % 2 == 0:
            last = lines[-1] if self.value else ""
            cx = inner.x + font(self.size).size(last)[0] + 1
            cy = inner.y + (len(lines) - 1) * line_h
            pygame.draw.line(surface, TEXT, (cx, cy + 2), (cx, cy + line_h - 2), 2)


class Cycle(Widget):
    """Click to go to the next option, right-click for the previous one."""

    def __init__(self, options, value=None, w=300, h=34, on_change=None):
        super().__init__(w, h)
        self.options = list(options)  # list of (value, label)
        self.index = 0
        self.on_change = on_change
        if value is not None:
            self.set(value)

    @property
    def value(self):
        return self.options[self.index][0]

    def set(self, value):
        for i, (v, _) in enumerate(self.options):
            if v == value:
                self.index = i
                return True
        return False

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3) and self.rect.collidepoint(event.pos):
            step = 1 if event.button == 1 else -1
            self.index = (self.index + step) % len(self.options)
            if self.on_change:
                self.on_change(self.value)
            return True
        return False

    def draw(self, surface):
        hover = self.rect.collidepoint(mouse_pos())
        pygame.draw.rect(surface, PANEL_HI if hover else PANEL, self.rect, border_radius=6)
        pygame.draw.rect(surface, BORDER, self.rect, 1, border_radius=6)
        label = fit_text(self.options[self.index][1], 18, self.rect.w - 50)
        text(surface, "<", (self.rect.x + 10, self.rect.y + 6), 18, MUTED)
        text(surface, ">", (self.rect.right - 20, self.rect.y + 6), 18, MUTED)
        text(surface, label, (self.rect.centerx, self.rect.y + 6), 18, center=True)


class Toggle(Widget):
    def __init__(self, value=False, w=90, h=34, labels=("No", "Yes")):
        super().__init__(w, h)
        self.value = bool(value)
        self.labels = labels

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            self.value = not self.value
            return True
        return False

    def draw(self, surface):
        color = (60, 140, 90) if self.value else PANEL
        pygame.draw.rect(surface, color, self.rect, border_radius=17)
        pygame.draw.rect(surface, BORDER, self.rect, 1, border_radius=17)
        r = self.rect.h // 2 - 4
        cx = self.rect.right - r - 5 if self.value else self.rect.x + r + 5
        pygame.draw.circle(surface, TEXT, (cx, self.rect.centery), r)
        label = self.labels[1] if self.value else self.labels[0]
        if self.value:
            text(surface, label, (self.rect.x + 12, self.rect.y + 7), 17)
        else:
            text(surface, label, (self.rect.right - 12, self.rect.y + 7), 17, MUTED, right=True)


class TilePicker(Widget):
    """A row of numbered boxes that toggle on and off."""

    def __init__(self, numbers, selected=(), box=42, gap=4, colors=None):
        self.numbers = list(numbers)
        self.box, self.gap = box, gap
        self.selected = set(selected)
        self.colors = colors  # function number -> base color
        super().__init__(len(self.numbers) * (box + gap) - gap, box)

    def box_rect(self, i):
        return pygame.Rect(self.rect.x + i * (self.box + self.gap), self.rect.y, self.box, self.box)

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            for i, n in enumerate(self.numbers):
                if self.box_rect(i).collidepoint(event.pos):
                    self.selected ^= {n}
                    return True
        return False

    def draw(self, surface):
        for i, n in enumerate(self.numbers):
            r = self.box_rect(i)
            base = self.colors(n) if self.colors else PANEL
            on = n in self.selected
            pygame.draw.rect(surface, (70, 165, 105) if on else base, r, border_radius=6)
            pygame.draw.rect(surface, (150, 240, 175) if on else BORDER, r, 2 if on else 1, border_radius=6)
            text(surface, n, (r.centerx, r.y + (r.h - font(18).get_height()) // 2), 18,
                 TEXT if on else MUTED, bold=on, center=True)


class TileValues(Widget):
    """One small number field per tile."""

    def __init__(self, numbers, values=None, box=42, gap=4, colors=None):
        self.numbers = list(numbers)
        self.colors = colors
        self.box, self.gap = box, gap
        values = values or {}
        self.fields = {n: TextField(values.get(n, ""), w=box, h=30, max_len=3, size=17) for n in self.numbers}
        super().__init__(len(self.numbers) * (box + gap) - gap, 50)

    def place(self, x, y):
        super().place(x, y)
        for i, n in enumerate(self.numbers):
            self.fields[n].place(x + i * (self.box + self.gap), y + 18)
        return self

    def values(self):
        return {n: f.value.strip() for n, f in self.fields.items()}

    def set_values(self, values):
        for n, f in self.fields.items():
            v = values.get(n, "")
            f.value = "" if v in (None, 0, "0") else str(v)

    def handle(self, event):
        return any(f.handle(event) for f in self.fields.values())

    def draw(self, surface):
        for i, n in enumerate(self.numbers):
            x = self.rect.x + i * (self.box + self.gap)
            r = pygame.Rect(x, self.rect.y, self.box, 16)
            pygame.draw.rect(surface, self.colors(n) if self.colors else PANEL, r, border_radius=4)
            text(surface, n, (r.centerx, r.y), 14, MUTED, center=True)
            self.fields[n].draw(surface)


def region_color(tile):
    return P1_COLOR if tile <= 5 else P2_COLOR
