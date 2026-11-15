"""Character registry and prompt builder: keeps looks identical across every shot."""
from __future__ import annotations

import os

from .manifest import Shot
from .util import read_json, write_json

STYLE = ("3D Pixar Disney style animated movie, soft golden-hour lighting, vibrant pastel colors, "
         "smooth natural character animation, shallow depth of field, high detail")

NEGATIVE = ("photorealistic humans, extra limbs, deformed paws, distorted face, melting, blurry, "
            "low quality, text, watermark, subtitles, logo, scary, violent, dark, flicker, static still image")

CHARACTERS = {
    "Novi": {
        "species": "baby bunny",
        "anchor": ("ultra-cute baby bunny named Novi, fluffy cream-white fur, long floppy ears with soft pink inside, "
                   "big sparkling brown eyes, chubby pink cheeks, wearing a mint-green cozy hoodie with pastel yellow "
                   "cuffs and soft blue sneakers"),
        "movement": "agile and bouncy, ears flopping with each hop, quick curious head turns",
        "voice_ref": "",
    },
    "Mimi": {
        "species": "bear cub",
        "anchor": ("adorable chubby baby bear cub named Mimi, warm honey-caramel fluffy fur, round ears, big sweet "
                   "dark eyes, wearing bright red denim overalls with large yellow buttons"),
        "movement": "chubby and goofy, belly jiggle, heavy soft footsteps, clumsy joyful arm swings",
        "voice_ref": "",
    },
    "Pip": {
        "species": "baby bluebird",
        "anchor": ("tiny cheerful baby bluebird named Pip, fluffy pastel sky-blue and white feathers, small yellow "
                   "beak, large curious eyes, wearing a miniature yellow acorn beanie"),
        "movement": "hyper-fast wing flutter, mid-air loops, tail feather twitches",
        "voice_ref": "",
    },
    "Toby": {
        "species": "baby turtle",
        "anchor": ("cute baby turtle named Toby, soft pastel green skin, big gentle green eyes, smooth shell with "
                   "pastel rainbow hexagon patterns, wearing tiny orange shoes"),
        "movement": "slow and steady, smooth gentle steps, slow expressive head nods",
        "voice_ref": "",
    },
}


def load_characters(path: str = "") -> dict:
    """Project overrides (characters.json) merged over built-in defaults."""
    chars = {k: dict(v) for k, v in CHARACTERS.items()}
    if path and os.path.exists(path):
        for name, cfg in read_json(path).items():
            chars.setdefault(name, {}).update(cfg)
    return chars


def save_default_characters(path: str) -> None:
    write_json(path, CHARACTERS)


def build_prompt(shot: Shot, characters: dict, talking: bool = False, style: str = STYLE,
                 max_characters: int = 2) -> tuple:
    """Return (positive, negative). Speaker is always first so the model focuses on them."""
    names = []
    if shot.speaker:
        names.append(shot.speaker)
    for n in shot.characters:
        if n not in names:
            names.append(n)
    names = names[:max_characters]
    anchors = [characters[n]["anchor"] for n in names if n in characters]
    parts = []
    if anchors:
        parts.append("; ".join(anchors))
    parts.append(shot.motion_prompt.strip())
    if talking and shot.speaker:
        parts.append(f"{shot.speaker} speaks to the camera, mouth moving naturally in sync with speech, expressive face")
    parts.append(shot.camera)
    parts.append(style)
    return ". ".join(p.rstrip(".") for p in parts if p), NEGATIVE


NO_TEXT = ("no text, no letters, no words, no signs, no captions, no watermark, no logo, no border, no frame, "
           "no thumbnail layout, no UI, no collage, single clean full-frame scene")


def still_prompt(shot: Shot, characters: dict, style: str = STYLE, max_characters: int = 2) -> str:
    """Prompt for one clean 16:9 keyframe image (the start frame the video model will animate)."""
    names = ([shot.speaker] if shot.speaker else []) + [n for n in shot.characters if n != shot.speaker]
    anchors = [characters[n]["anchor"] for n in names[:max_characters] if n in characters]
    parts = ["; ".join(anchors), shot.action.strip(), shot.camera, style, "16:9 widescreen, full frame",
             NO_TEXT]
    return ". ".join(p.rstrip(".") for p in parts if p)


def sheet_prompt(name: str, characters: dict, style: str = STYLE) -> str:
    """Character reference sheet prompt: same character, several poses on a plain background."""
    return (f"Character reference sheet of {characters[name]['anchor']}. Show the same character in front view, "
            f"three-quarter view, side view and back view, plus 4 expressions (happy, surprised, sad, laughing), "
            f"neutral standing pose, plain soft pastel background, consistent proportions and colors in every view, "
            f"{style}. No text labels, no names, no captions, no watermark, no logo, no border.")
