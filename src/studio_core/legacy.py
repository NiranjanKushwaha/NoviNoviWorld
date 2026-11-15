"""Import the hard-coded EPISODE_SCENES from the original studio.py (no code execution)."""
from __future__ import annotations

import ast

from .manifest import Episode, Shot, stable_seed
from .prompts import CHARACTERS

REF_BY_SCENE = {
    1: "assets/characters/novi_and_friends.jpg", 2: "assets/characters/novi_and_friends.jpg",
    3: "assets/characters/novi_and_friends.jpg", 4: "assets/characters/novi_and_friends.jpg",
    5: "assets/characters/novi_treehouse.jpg", 6: "assets/characters/novi_treehouse.jpg",
    7: "assets/characters/rainbow_slide.jpg", 8: "assets/characters/rainbow_slide.jpg",
}

# Motion prompts derived from docs/CHARACTER_ACTION_PHYSICS_BIBLE.md, one per legacy scene.
MOTION = {
    1: "Novi runs and hops along a soft mossy forest path, ears flapping with wind, paws kicking up tiny glowing flower petals, natural weight shift with each hop, wide-eyed excitement",
    2: "Mimi performs a rhythmic belly-wiggle dance on green grass, shaking hips side to side, throwing hands in the air and laughing, munching a berry, fur reacting to the moves",
    3: "Pip flutters rapidly in mid-air, doing a small loop and pointing a wing up to a glowing golden star-fruit on the highest branch",
    4: "Toby takes slow steady steps across marshmallow stepping stones by a crystal brook, nodding encouragement with a gentle smile",
    5: "Novi climbs the rough bark of a giant oak tree, front paws gripping, pulling body weight upward, kicking back legs onto a mossy branch, reaching toward a glowing star-fruit",
    6: "Novi dances a joyful victory dance on a wooden treehouse balcony, stomping tiny blue sneakers, spinning around, high-fiving friends and waving over the railing",
    7: "Novi slides down a curved translucent rainbow water slide at speed, leaning into the banked turn, water droplets spraying, ears streaming back, ecstatic smile",
    8: "Novi lands in a giant fluffy marshmallow pit with a deep soft bounce, pops back up holding a golden star-fruit, Mimi runs in and gives a tight squishy hug, heart bubbles pop around them",
}

CAMERA = {
    1: "tracking shot following forward", 2: "static wide shot, slight push-in", 3: "low angle looking up, slow tilt",
    4: "medium shot, gentle pan", 5: "upward crane shot following the climb", 6: "medium shot, slow orbit",
    7: "fast tracking shot along the slide", 8: "wide shot, slow push-in",
}


def load_legacy_scenes(studio_py_path: str) -> list:
    with open(studio_py_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "EPISODE_SCENES" for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError("EPISODE_SCENES not found in " + studio_py_path)


def episode_from_legacy(scenes: list, episode_id: str, title: str) -> Episode:
    shots = []
    for sc in scenes:
        n = int(sc["scene"])
        text = f"{sc.get('hindi', '')} {sc.get('english', '')}"
        cast = [sc["speaker"]] + [c for c in CHARACTERS if c != sc["speaker"] and c in text]
        sid = f"s{n:02d}"
        shots.append(Shot(
            shot_id=sid, scene=n, speaker=sc["speaker"], action=sc["action"],
            dialogue={"hindi": sc["hindi"], "english": sc["english"]},
            characters=cast, ref_image=REF_BY_SCENE.get(n, "assets/characters/novi_and_friends.jpg"),
            motion_prompt=MOTION.get(n, sc["action"]), camera=CAMERA.get(n, "medium shot"),
            seed=stable_seed(episode_id, sid),
        ))
    return Episode(episode_id=episode_id, title=title, languages=["hindi", "english"], fps=24, shots=shots)
