"""Loads and caches the game's sprites from the assets folder."""

import os
import re

import pygame

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_cache = {}


def sprite(name, width=None, height=None, ext="png", alpha=True):
    """Return assets/<name>.<ext> scaled to the given width and/or height.

    With only one of width/height the aspect ratio is kept. Returns None if
    the file is missing, so callers can fall back to shapes.
    """
    key = (name, width, height, ext)
    if key in _cache:
        return _cache[key]
    path = os.path.join(ASSETS, f"{name}.{ext}")
    try:
        img = pygame.image.load(path)
        img = img.convert_alpha() if alpha else img.convert()
    except (pygame.error, FileNotFoundError):
        return None  # not cached, so a later call (e.g. once a window exists) can retry
    w, h = img.get_size()
    if width and not height:
        height = round(h * width / w)
    elif height and not width:
        width = round(w * height / h)
    if width and height and (width, height) != (w, h):
        img = pygame.transform.smoothscale(img, (width, height))
    _cache[key] = img
    return img


def terrain(player_index, width):
    return sprite(f"terrain_p{player_index + 1}", width=width)


def wizard(player_index, scale):
    name = f"player_p{player_index + 1}"
    full = sprite(name)
    if full is None:
        return None
    return sprite(name, width=max(1, round(full.get_width() * scale)))


def background(size):
    return sprite("background", size[0], size[1], ext="jpg", alpha=False)


def card_template(tier):
    return sprite(f"card_{tier}")


def art_name(card):
    """Card art in assets/art: the card's "art" key, else its name in lower case
    with underscores ("Magic knife" -> magic_knife.png)."""
    if card.get("art"):
        name = card["art"]
        return name[:-4] if name.lower().endswith(".png") else name
    return re.sub(r"[^a-z0-9]+", "_", card["name"].lower()).strip("_")


def card_art(card):
    return sprite("art/" + art_name(card))


def distance_meter():
    return sprite("distance_meter")
