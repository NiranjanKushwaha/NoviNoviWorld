"""Headless Blender shot builder: procedural kid characters, motion, lip-sync, camera, render.

Run:  blender -b -P render_shot.py -- spec.json
No external assets are required; an optional backdrop image plane can be supplied in the spec.
"""
import json
import math
import os
import random
import sys

import bpy  # noqa: F401  (must come before bmesh when used as a module)
import bmesh  # noqa: E402

TAU = math.tau


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def lerp(a, b, t):
    return a + (b - a) * t


def ease(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


# ----------------------------------------------------------------- materials / primitives
_MATS = {}


def mat(name, rgb, rough=0.55, emit=0.0, fuzz=0.0):
    key = (name, tuple(rgb), rough, emit, fuzz)
    if key in _MATS:
        return _MATS[key]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]

    def put(k, v):
        if k in b.inputs:
            b.inputs[k].default_value = v

    put("Base Color", (rgb[0], rgb[1], rgb[2], 1))
    put("Roughness", rough)
    if emit:
        put("Emission Color", (rgb[0], rgb[1], rgb[2], 1))
        put("Emission Strength", emit)
    if fuzz:
        n = nt.nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = 160
        n.inputs["Detail"].default_value = 5
        bp = nt.nodes.new("ShaderNodeBump")
        bp.inputs["Strength"].default_value = fuzz
        bp.inputs["Distance"].default_value = 0.01
        nt.links.new(n.outputs["Fac"], bp.inputs["Height"])
        nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
        put("Sheen Weight", 0.5)
    _MATS[key] = m
    return m


def _link(o, parent, loc, scale, m, rot=None):
    bpy.context.scene.collection.objects.link(o)
    o.location = loc
    o.scale = scale
    if rot:
        o.rotation_euler = rot
    if m is not None:
        o.data.materials.append(m)
    if parent is not None:
        o.parent = parent
    return o


def sphere(name, loc, scale, m, parent=None, seg=24, rot=None):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=max(6, seg // 2), radius=1.0)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    return _link(bpy.data.objects.new(name, me), parent, loc, scale, m, rot)


def cone(name, loc, r1, r2, depth, m, parent=None, rot=None, seg=16, scale=(1, 1, 1)):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r1, radius2=r2, depth=depth)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    return _link(bpy.data.objects.new(name, me), parent, loc, scale, m, rot)


def box(name, loc, scale, m, parent=None, rot=None):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return _link(bpy.data.objects.new(name, me), parent, loc, scale, m, rot)


def empty(name, loc=(0, 0, 0), parent=None):
    o = bpy.data.objects.new(name, None)
    o.empty_display_size = 0.1
    bpy.context.scene.collection.objects.link(o)
    o.location = loc
    if parent is not None:
        o.parent = parent
    return o


# ----------------------------------------------------------------- characters
PALETTE = {
    "bunny": dict(fur=(0.98, 0.93, 0.86), inner=(1.0, 0.62, 0.72), cloth=(0.5, 0.84, 0.7), cloth2=(0.38, 0.7, 0.58)),
    "bear": dict(fur=(0.82, 0.52, 0.2), light=(0.97, 0.8, 0.55), cloth=(0.82, 0.16, 0.12), inner=(1.0, 0.62, 0.55)),
    "bird": dict(fur=(0.42, 0.68, 0.98), light=(0.98, 0.98, 1.0), beak=(1.0, 0.6, 0.15), hat=(0.55, 0.32, 0.14)),
    "turtle": dict(fur=(0.56, 0.86, 0.5), light=(0.98, 0.92, 0.7), shell=(0.3, 0.62, 0.42)),
}
RAINBOW = [(1, .25, .25), (1, .6, .15), (1, .9, .2), (.4, .85, .35), (.3, .6, 1), (.6, .4, 1)]
DARK = (0.06, 0.04, 0.05)


def species_of(text):
    t = (text or "").lower()
    for k in ("bunny", "rabbit", "bear", "bird", "turtle"):
        if k in t:
            return {"rabbit": "bunny"}.get(k, k)
    return "bunny"


class Kid:
    """One character: a joint hierarchy animated procedurally (no armature needed)."""

    def __init__(self, name, species):
        self.name, self.sp = name, species
        P = PALETTE[species]
        fur = mat(f"{name}_fur", P["fur"], 0.8, fuzz=0.25)
        light = mat(f"{name}_light", P.get("light", P["fur"]), 0.8, fuzz=0.2)
        pink = mat("pink", P.get("inner", (1.0, 0.62, 0.7)), 0.7)
        dark = mat("dark", DARK, 0.25)
        white = mat("eyewhite", (1, 1, 1), 0.2)
        self.root = empty(f"{name}_root")
        self.sq = empty(f"{name}_sq", (0, 0, 0), self.root)
        self.bodyp = empty(f"{name}_bodyp", (0, 0, 0.3), self.sq)
        self.headp = empty(f"{name}_headp", (0, 0, 0.55), self.bodyp)
        cloth = mat(f"{name}_cloth", P.get("cloth", P["fur"]), 0.7, fuzz=0.12)
        # body
        body_m = cloth if species == "bunny" else fur
        sphere(f"{name}_body", (0, 0, 0.28), (0.40, 0.34, 0.38), body_m, self.bodyp)
        # head
        hc = (0, 0, 0.38)
        head_m = fur
        sphere(f"{name}_head", hc, (0.52, 0.47, 0.46), head_m, self.headp, seg=32)
        # face
        self.eyes = empty(f"{name}_eyes", (0, 0, hc[2] + 0.07), self.headp)
        for s in (-1, 1):
            ex = 0.18 * s
            sphere(f"{name}_ew", (ex, -0.405, 0), (0.105, 0.07, 0.125), white, self.eyes)
            sphere(f"{name}_pu", (ex, -0.462, 0), (0.068, 0.04, 0.09), dark, self.eyes)
            sphere(f"{name}_hl", (ex + 0.025, -0.495, 0.04), (0.022, 0.015, 0.025), white, self.eyes, seg=8)
            sphere(f"{name}_ch", (0.3 * s, -0.36, hc[2] - 0.1 + 0.0), (0.07, 0.025, 0.05), mat("cheek", (1, 0.55, 0.6), 0.9), self.headp, seg=10)
        my = -0.44
        nz = hc[2] - 0.05
        if species == "bear":
            sphere(f"{name}_muzzle", (0, -0.36, hc[2] - 0.1), (0.22, 0.14, 0.16), light, self.headp)
            my = -0.488
            sphere(f"{name}_nose", (0, -0.5, nz + 0.01), (0.055, 0.035, 0.04), dark, self.headp, seg=12)
        elif species == "bird":
            cone(f"{name}_beak", (0, -0.5, nz), 0.1, 0.0, 0.2, mat("beak", P["beak"], 0.4), self.headp, rot=(math.pi / 2, 0, 0))
            my = -0.46
        else:
            sphere(f"{name}_nose", (0, -0.455, nz), (0.045, 0.03, 0.035), pink if species == "bunny" else dark, self.headp, seg=12)
        self.mouth = empty(f"{name}_mouth", (0, my, hc[2] - 0.16 - (0.01 if species == "bird" else 0)), self.headp)
        sphere(f"{name}_mouthm", (0, 0, 0), (0.08, 0.025, 0.02), mat("mouth", (0.45, 0.05, 0.08), 0.4), self.mouth, seg=12)
        sphere(f"{name}_tongue", (0, 0.0, -0.01), (0.045, 0.02, 0.012), mat("tongue", (1, 0.4, 0.5), 0.5), self.mouth, seg=8)
        # ears / extras
        self.earL = self.earR = None
        if species == "bunny":
            for s, attr in ((1, "earL"), (-1, "earR")):
                ep = empty(f"{name}_{attr}", (0.2 * s, 0, hc[2] + 0.4), self.headp)
                sphere(f"{name}_ear", (0, 0, 0.34), (0.10, 0.07, 0.36), fur, ep)
                sphere(f"{name}_earin", (0, -0.04, 0.34), (0.055, 0.03, 0.28), pink, ep)
                ep.rotation_euler = (0, 0.22 * s, 0)
                setattr(self, attr, ep)
            sphere(f"{name}_tail", (0, 0.34, 0.12), (0.15, 0.15, 0.15), mat("tailw", (1, 1, 1), 0.9, fuzz=0.3), self.bodyp)
            sphere(f"{name}_hood", (0, 0.12, 0.64), (0.3, 0.14, 0.2), cloth, self.bodyp)
            sphere(f"{name}_pocket", (0, -0.335, 0.15), (0.2, 0.03, 0.1), mat("pocket", P["cloth2"], 0.7), self.bodyp)
        elif species == "bear":
            for s, attr in ((1, "earL"), (-1, "earR")):
                ep = empty(f"{name}_{attr}", (0.36 * s, 0, hc[2] + 0.3), self.headp)
                sphere(f"{name}_ear", (0, 0, 0.06), (0.15, 0.1, 0.15), fur, ep)
                sphere(f"{name}_earin", (0, -0.05, 0.06), (0.08, 0.04, 0.08), pink, ep)
                setattr(self, attr, ep)
            sphere(f"{name}_belly", (0, -0.18, 0.22), (0.26, 0.2, 0.28), light, self.bodyp)
            sphere(f"{name}_overall", (0, 0, 0.15), (0.415, 0.355, 0.2), cloth, self.bodyp)
        elif species == "bird":
            for i, dx in enumerate((-0.07, 0.0, 0.07)):
                sphere(f"{name}_tuft", (dx, -0.02, hc[2] + 0.46 + (0.03 if i == 1 else 0)), (0.03, 0.03, 0.08), fur, self.headp, seg=8)
            sphere(f"{name}_hat", (0, 0, hc[2] + 0.37), (0.27, 0.25, 0.17), mat("hat", P["hat"], 0.6), self.headp)
            sphere(f"{name}_hatstem", (0, 0, hc[2] + 0.55), (0.04, 0.04, 0.06), mat("stem", (0.35, 0.22, 0.1), 0.6), self.headp, seg=8)
            sphere(f"{name}_tail", (0, 0.3, 0.15), (0.14, 0.2, 0.1), fur, self.bodyp)
            sphere(f"{name}_belly", (0, -0.2, 0.25), (0.27, 0.2, 0.28), light, self.bodyp)
        elif species == "turtle":
            sphere(f"{name}_shell", (0, 0.16, 0.38), (0.5, 0.42, 0.34), mat("shell", P["shell"], 0.45), self.bodyp)
            for i, c in enumerate(RAINBOW):
                a = i / len(RAINBOW) * TAU
                sphere(f"{name}_sp", (0.26 * math.cos(a), 0.16 + 0.22 * math.sin(a), 0.5 + 0.1 * (1 if i % 2 else 0)),
                       (0.1, 0.1, 0.05), mat(f"sp{i}", c, 0.4), self.bodyp, seg=10)
            sphere(f"{name}_belly", (0, -0.2, 0.22), (0.28, 0.2, 0.28), light, self.bodyp)
        # arms
        self.armL = empty(f"{name}_armL", (0.40, 0, 0.38), self.bodyp)
        self.armR = empty(f"{name}_armR", (-0.40, 0, 0.38), self.bodyp)
        arm_m = {"bunny": cloth, "bear": fur, "bird": fur, "turtle": fur}[species]
        hand_m = {"bunny": fur, "bear": fur, "bird": fur, "turtle": fur}[species]
        for a in (self.armL, self.armR):
            sphere(f"{name}_arm", (0, 0, -0.17), (0.11 if species != "bird" else 0.07, 0.11, 0.2), arm_m, a)
            sphere(f"{name}_hand", (0, 0, -0.36), (0.1, 0.1, 0.1), hand_m, a, seg=14)
        # legs
        self.legL = empty(f"{name}_legL", (0.2, 0, 0.28), self.sq)
        self.legR = empty(f"{name}_legR", (-0.2, 0, 0.28), self.sq)
        foot_m = mat("foot", P.get("beak", P["fur"]), 0.5) if species == "bird" else fur
        for l in (self.legL, self.legR):
            sphere(f"{name}_leg", (0, 0, -0.12), (0.15, 0.15, 0.17), foot_m if species == "bird" else fur, l)
            sphere(f"{name}_foot", (0, -0.07, -0.25), (0.17, 0.22, 0.1), foot_m, l, seg=14)

    # pose application ---------------------------------------------------
    def pose(self, p, f):
        ob = self.root
        ob.location = (p["x"], p["y"], p["z"])
        ob.rotation_euler = (p["rx"], p["ry"], p["rz"])
        self.sq.scale = (p["sx"], p["sx"], p["sz"])
        self.bodyp.rotation_euler = (p["brx"], p["bry"], p["brz"])
        self.headp.rotation_euler = (p["hrx"], p["hry"], p["hrz"])
        self.armL.rotation_euler = (-p["als"], -p["al"], 0)
        self.armR.rotation_euler = (-p["ars"], p["ar"], 0)
        self.legL.rotation_euler = (-p["lls"], 0, 0)
        self.legR.rotation_euler = (-p["lrs"], 0, 0)
        self.eyes.scale = (1, 1, p["blink"])
        mo, mw = p["mo"], p["mw"]
        self.mouth.scale = (mw, 1, 0.35 + 5.5 * mo)
        if self.earL:
            base = 0.22 if self.sp == "bunny" else 0.0
            self.earL.rotation_euler = (p["ex"], base + p["ey"], 0)
            self.earR.rotation_euler = (p["ex"], -base - p["ey"], 0)
        for o in (self.root, self.sq, self.bodyp, self.headp, self.armL, self.armR, self.legL, self.legR, self.eyes, self.mouth):
            for path in ("location", "rotation_euler", "scale"):
                if path == "location" and o is not self.root:
                    continue
                o.keyframe_insert(path, frame=f)
        if self.earL:
            for e in (self.earL, self.earR):
                e.keyframe_insert("rotation_euler", frame=f)


# ----------------------------------------------------------------- motion library
def base_pose():
    return dict(x=0, y=0, z=0, rx=0, ry=0, rz=0, sx=1, sz=1, brx=0, bry=0, brz=0, hrx=0, hry=0, hrz=0,
                al=0.15, ar=0.15, als=0, ars=0, lls=0, lrs=0, ex=0, ey=0, blink=1, mo=0, mw=1)


def squash(air):
    sz = 0.86 + 0.2 * air
    return 1 / math.sqrt(sz), sz


def hop(ph, amp):
    air = abs(math.sin(math.pi * (ph % 1.0)))
    return amp * air, air


def m_idle(t, u, C):
    b = math.sin(t * TAU * 0.5 + C["phase"])
    return dict(sz=1 + 0.025 * b, sx=1 - 0.012 * b, hrz=0.12 * math.sin(t * 1.3 + C["phase"]), brz=0.03 * math.sin(t))


def m_bounce(t, u, C, amp=0.14, f=2.0, arms=1.0):
    ph = t * f + C["phase"]
    z, air = hop(ph, amp)
    sx, sz = squash(air)
    s = math.sin(ph * TAU)
    return dict(z=z, sx=sx, sz=sz, al=0.4 + arms * (0.5 + 0.5 * s), ar=0.4 + arms * (0.5 - 0.5 * s), lls=0.4 * air, lrs=0.4 * air,
                hrz=0.15 * math.sin(ph * math.pi))


def m_cheer(t, u, C):
    p = m_bounce(t, u, C, 0.16, 1.8, 1.0)
    p["al"] = p["ar"] = 2.4 + 0.3 * math.sin(t * 9 + C["phase"])
    return p


def m_hop_run(t, u, C):
    n = max(2, int(C["T"] * 1.8))
    ph = u * n
    z, air = hop(ph, 0.3)
    sx, sz = squash(air)
    x0, x1 = -2.0, 2.0
    sw = math.sin(ph * TAU)
    return dict(x=lerp(x0, x1, ease(u * 0.95 + 0.025)), z=z, sx=sx, sz=sz, rz=0.55, brx=-0.12, hrz=-0.2,
                als=0.7 * sw, ars=-0.7 * sw, lls=0.9 * air, lrs=0.9 * air, al=0.3, ar=0.3)


def m_dance(t, u, C):
    ph = t * 2.0 + C["phase"]
    z, air = hop(ph, 0.12)
    sx, sz = squash(air)
    s = math.sin(ph * math.pi)
    spin = TAU * ease((u - 0.45) / 0.3) if C["role"] == "lead" else 0.0
    return dict(z=z, sx=sx, sz=sz, rz=0.35 * s + spin, bry=0.18 * s, brz=0.2 * s, hrz=-0.25 * s,
                al=1.0 + 1.1 * (0.5 + 0.5 * s), ar=1.0 + 1.1 * (0.5 - 0.5 * s), als=0.3 * s, ars=-0.3 * s,
                lls=0.5 * air, lrs=0.5 * air)


def m_belly(t, u, C):
    p = m_dance(t, u, C)
    p["al"] = p["ar"] = 1.1
    p["als"] = p["ars"] = 0.9
    p["bry"] = 0.0
    p["sx"] *= 1 + 0.05 * math.sin(t * TAU * 2)
    return p


def m_flutter(t, u, C):
    flap = math.sin(t * TAU * 6.5)
    cx = 0.9 * math.sin(u * TAU)
    cz = 1.5 + 0.35 * math.sin(u * TAU * 1.0 + 1.0) + 0.1 * math.sin(t * 4)
    look = -0.55 * ease(math.sin(clamp(u * 1.3, 0, 1) * math.pi))
    return dict(x=cx, z=cz, rz=0.3 * math.cos(u * TAU), bry=0.18 * math.sin(u * TAU), hrx=look, hrz=0.15 * math.sin(t * 2),
                al=0.9 + 0.8 * flap, ar=0.9 + 0.8 * flap, lls=0.7, lrs=0.7, brx=-0.15)


def m_walk_slow(t, u, C):
    w = math.sin(t * TAU * 0.9)
    return dict(x=lerp(-1.3, 0.3, ease(u)), z=0.03 * abs(w), rz=0.35, lls=0.45 * w, lrs=-0.45 * w, hrx=0.08 * math.sin(t * 1.6),
                hrz=-0.15, brz=0.05 * w, als=0.3 * w, ars=-0.3 * w)


def m_climb(t, u, C):
    n = 5
    ph = u * n
    seg = int(min(ph, n - 1e-6))
    f = ph - seg
    z0 = seg * 0.85
    z = lerp(z0, z0 + 0.85, ease(f)) + 0.05 * math.sin(f * math.pi)
    air = math.sin(f * math.pi)
    side = 1 if seg % 2 == 0 else -1
    reach = 0.5 + 0.5 * math.sin(f * math.pi)
    return dict(x=0.15 * side * math.sin(f * math.pi), y=-0.1, z=z, brx=-0.15, hrx=-0.3,
                al=2.6 if side > 0 else 1.4, ar=1.4 if side > 0 else 2.6, als=0.2 * reach, ars=0.2 * reach,
                lls=0.8 * air, lrs=0.2, sx=1 + 0.03 * air, sz=1 - 0.03 * air)


SLIDE_A, SLIDE_B = (-3.4, 0.4, 3.0), (3.2, -0.6, 0.15)


def slide_path(s):
    s = clamp(s)
    x = lerp(SLIDE_A[0], SLIDE_B[0], s)
    y = lerp(SLIDE_A[1], SLIDE_B[1], s) + 0.55 * math.sin(s * TAU)
    z = lerp(SLIDE_A[2], SLIDE_B[2], s ** 1.15) + 0.0
    return x, y, z


def m_slide(t, u, C):
    if u < 0.22:
        k = u / 0.22
        return dict(x=SLIDE_A[0] - 0.5, y=SLIDE_A[1], z=SLIDE_A[2], sz=1 - 0.15 * math.sin(k * math.pi * 0.5),
                    sx=1 + 0.07 * k, al=2.3, ar=2.3, lls=0.3, rz=0.5)
    if u < 0.36:
        k = ease((u - 0.22) / 0.14)
        x0, y0, z0 = SLIDE_A[0] - 0.5, SLIDE_A[1], SLIDE_A[2]
        x1, y1, z1 = slide_path(0.04)
        return dict(x=lerp(x0, x1, k), y=lerp(y0, y1, k), z=lerp(z0, z1, k) + 0.7 * math.sin(k * math.pi), rz=0.5 + k * 0.3,
                    al=2.7, ar=2.7, lls=0.6, lrs=0.6, bry=0.0, hrx=-0.1)
    s = (u - 0.36) / 0.64
    x, y, z = slide_path(0.04 + 0.96 * s)
    x2, y2, _ = slide_path(0.04 + 0.96 * min(1, s + 0.03))
    ang = math.atan2(x2 - x, -(y2 - y) + 1e-6)
    return dict(x=x, y=y, z=z + 0.05, rz=clamp(ang, -1.0, 1.2), rx=-0.18, brx=-0.25, al=2.6 + 0.2 * math.sin(t * 8), ar=2.6 - 0.2 * math.sin(t * 8),
                lls=0.9, lrs=0.9, hrx=-0.1)


def m_share(t, u, C):
    p = m_bounce(t, u, C, 0.08, 1.4, 0.5)
    k = ease((u - 0.6) / 0.3)
    side = C["side"]
    p["x"] = -side * 0.35 * k
    p["rz"] = side * (0.55 + 0.4 * k)
    p["al"] = p["ar"] = lerp(0.6, 1.0, k)
    p["als"] = p["ars"] = lerp(0.0, 1.1, k)
    return p


def m_react(t, u, C):
    p = m_bounce(t, u, C, 0.1, 2.0, 0.6)
    return p


MOTIONS = dict(idle=m_idle, bounce=m_bounce, cheer=m_cheer, hop_run=m_hop_run, dance=m_dance, belly=m_belly,
               flutter=m_flutter, walk_slow=m_walk_slow, climb=m_climb, slide=m_slide, share=m_share, react=m_react)

# what a supporting character does while the lead performs a given motion
SUPPORT = dict(hop_run="react", dance="dance", belly="dance", flutter="react", walk_slow="cheer", climb="react",
               slide="react", share="share", cheer="cheer", idle="idle", bounce="react", react="react")


def make_poses(kid, role, slot, n_slots, spec, rng, speaker_pos):
    fps, N = spec["fps"], spec["frames"]
    T = N / fps
    lead_motion = spec["motion"]
    mname = lead_motion if role == "lead" else SUPPORT.get(lead_motion, "react")
    fn = MOTIONS[mname]
    side = -1 if slot == 0 else 1
    bx = 0.0 if n_slots == 1 else (-1.0 if slot == 0 else 1.15)
    by = 0.0 if slot == 0 else 0.4
    if lead_motion in ("hop_run", "flutter", "walk_slow", "climb", "slide") and role == "lead":
        bx, by = 0.0, 0.0
    if lead_motion == "walk_slow" and role != "lead":
        bx, by = 1.6, 0.2
    C = dict(T=T, role=role, phase=rng.random(), side=side)
    blink_at = []
    tt = rng.uniform(0.6, 1.8)
    while tt < T:
        blink_at.append(int(tt * fps))
        tt += rng.uniform(2.2, 3.8)
    poses = []
    for f in range(N):
        t, u = f / fps, f / max(1, N - 1)
        p = base_pose()
        p.update(fn(t, u, C))
        p["x"] += bx
        p["y"] += by
        if role != "lead" and speaker_pos is not None:
            ang = math.atan2(speaker_pos[0] - p["x"], -(speaker_pos[1] - p["y"]) + 1e-6)
            p["hrz"] = clamp(ang - p["rz"], -0.7, 0.7) * 0.8
        for b in blink_at:
            d = f - b
            if 0 <= d < 5:
                p["blink"] = 1 - 0.9 * (1 - abs(d - 2) / 2.0)
        if role == "lead":
            mo, mw = spec["mouth"][f] if f < len(spec["mouth"]) else (0.0, 0.5)
            p["mo"], p["mw"] = mo, 0.85 + 0.45 * mw
            p["hrx"] += 0.07 * mo
            p["z"] += 0.012 * mo
        else:
            p["mo"], p["mw"] = 0.0, 1.25
        poses.append(p)
    # secondary motion: ears lag the vertical velocity, then a light smoothing pass
    ex = 0.0
    for f in range(N):
        vz = (poses[min(N - 1, f + 1)]["z"] - poses[max(0, f - 1)]["z"]) * fps / 2.0
        ex = lerp(ex, clamp(-0.10 * vz, -0.55, 0.55), 0.35)
        poses[f]["ex"] = ex + 0.05 * math.sin(f / fps * 3 + C["phase"] * 6)
        poses[f]["ey"] = 0.18 * abs(ex)
    return poses


# ----------------------------------------------------------------- environment
def build_env(scene_no, rng, motion, backdrop=""):
    g = mat("grass", (0.42, 0.8, 0.26), 0.9, fuzz=0.15)
    ground = bpy.data.objects.new("ground", bpy.data.meshes.new("ground"))
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=2, y_segments=2, size=40)
    bm.to_mesh(ground.data)
    bm.free()
    bpy.context.scene.collection.objects.link(ground)
    ground.data.materials.append(g)
    on_platform = motion in ("dance",) and scene_no == 6
    ground.location = (0, 0, -6.0 if on_platform else -0.02)
    trunk_m = mat("trunk", (0.45, 0.28, 0.14), 0.9, fuzz=0.3)
    leaf = [mat(f"leaf{i}", c, 0.8, fuzz=0.1) for i, c in enumerate([(0.18, 0.55, 0.2), (0.25, 0.65, 0.25), (0.15, 0.48, 0.3)])]
    far_leaf = mat("farleaf", (0.42, 0.62, 0.55), 0.9)
    # depth-layered trees (far ones hazier)
    for i in range(26):
        x = rng.uniform(-16, 16)
        y = rng.uniform(5, 26)
        if scene_no == 5 and abs(x) < 3.0 and y < 9:
            continue
        s = rng.uniform(0.8, 1.5)
        far = y > 14
        h = 3.4 * s
        z0 = -6.0 if on_platform else 0.0
        cone(f"trunk{i}", (x, y, z0 + h / 2), 0.3 * s, 0.22 * s, h, trunk_m)
        for j in range(3):
            sphere(f"crown{i}_{j}", (x + rng.uniform(-0.5, 0.5), y + rng.uniform(-0.3, 0.3), z0 + h + 0.5 + j * 0.5 * s),
                   (1.5 * s, 1.5 * s, 1.0 * s), far_leaf if far else leaf[(i + j) % 3], seg=14)
    for i in range(5):  # soft hills
        sphere(f"hill{i}", (-18 + i * 9 + rng.uniform(-2, 2), 30, -3), (11, 8, 7), mat(f"hill{i}", (0.55, 0.8, 0.62), 0.9), seg=16)
    # dressing near the camera: flowers + glowing mushrooms
    if not on_platform:
        for i in range(70):
            x, y = rng.uniform(-9, 9), rng.uniform(-3, 8)
            if abs(x) < 0.9 and abs(y) < 0.8:
                continue
            c = RAINBOW[i % len(RAINBOW)]
            cone(f"stem{i}", (x, y, 0.17), 0.015, 0.015, 0.34, mat("stem", (0.2, 0.55, 0.2), 0.8))
            sphere(f"fl{i}", (x, y, 0.38), (0.09, 0.09, 0.05), mat(f"fl{i % 6}", c, 0.5, emit=0.35), seg=10)
        for i in range(8):
            x, y = rng.choice([-1, 1]) * rng.uniform(2.5, 8), rng.uniform(0.5, 7)
            cone(f"mst{i}", (x, y, 0.2), 0.08, 0.1, 0.4, mat("mst", (0.95, 0.9, 0.8), 0.8))
            sphere(f"mcap{i}", (x, y, 0.45), (0.28, 0.28, 0.16), mat(f"mcap{i % 3}", [(0.3, 0.7, 1), (1, 0.4, 0.8), (0.6, 0.4, 1)][i % 3], 0.4, emit=0.8), seg=14)
    # story props
    if scene_no == 5 or motion == "climb":
        cone("bigtrunk", (0, 1.25, 3.5), 0.95, 0.85, 7.0, trunk_m, seg=28)
        for k in range(6):
            sx = 1 if k % 2 == 0 else -1
            box(f"ledge{k}", (0.6 * sx, 0.55, 0.45 + k * 0.85), (0.6, 0.35, 0.12), trunk_m)
        sphere("bigcrown", (0, 1.25, 8.0), (3.2, 3.0, 1.8), leaf[1], seg=20)
    if scene_no in (6, 7) or motion in ("slide",):
        wood = mat("wood", (0.72, 0.5, 0.28), 0.8, fuzz=0.15)
        if motion != "slide":
            box("deck", (0, 0, -0.18), (5.2, 3.2, 0.2), wood)
            for i, x in enumerate((-2.5, -1.25, 0, 1.25, 2.5)):
                box(f"post{i}", (x, -1.5, 0.45), (0.1, 0.1, 0.9), wood)
            box("rail", (0, -1.5, 0.9), (5.2, 0.08, 0.1), wood)
            sphere("roofleaf", (0, 2.0, 2.6), (3.6, 2.4, 1.2), leaf[0], seg=16)
        else:
            box("topdeck", (SLIDE_A[0] - 0.6, SLIDE_A[1], SLIDE_A[2] - 0.2), (2.0, 1.6, 0.2), wood)
            for i in range(26):  # rainbow slide built from short coloured strips
                s0 = i / 25
                x, y, z = slide_path(s0)
                x1, y1, z1 = slide_path(min(1, s0 + 0.04))
                ang = math.atan2(z1 - z, x1 - x)
                for ci, c in enumerate(RAINBOW):
                    box(f"sl{i}_{ci}", (x, y + (ci - 2.5) * 0.12, z - 0.12), (0.62, 0.12, 0.06), mat(f"rb{ci}", c, 0.3, emit=0.15),
                        rot=(0, -ang, 0))
    if scene_no in (3, 5, 6, 8):
        sphere("starfruit", (2.2 if scene_no == 3 else 1.5, 3.0 if scene_no == 3 else 2.0, 5.2 if scene_no == 3 else 2.4),
               (0.35, 0.35, 0.35), mat("star", (1.0, 0.85, 0.2), 0.3, emit=2.5), seg=12)
    if scene_no == 8:
        for i in range(10):
            sphere(f"mallow{i}", (rng.uniform(-3, 3), rng.uniform(0.5, 3), 0.15), (0.5, 0.5, 0.3), mat("mallow", (1, 0.93, 0.95), 0.7), seg=12)
    if backdrop and os.path.exists(backdrop):
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
        me = bpy.data.meshes.new("bd")
        bm.to_mesh(me)
        bm.free()
        o = bpy.data.objects.new("backdrop", me)
        bpy.context.scene.collection.objects.link(o)
        o.location, o.scale = (0, 30, 5), (112, 63, 1)
        o.rotation_euler = (math.pi / 2, 0, 0)
        m = bpy.data.materials.new("bdm")
        m.use_nodes = True
        nt = m.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        im = nt.nodes.new("ShaderNodeTexImage")
        im.image = bpy.data.images.load(backdrop)
        em = nt.nodes.new("ShaderNodeEmission")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(im.outputs["Color"], em.inputs["Color"])
        nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
        o.data.materials.append(m)


def build_sky():
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=90)
    me = bpy.data.meshes.new("sky")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("sky", me)
    bpy.context.scene.collection.objects.link(o)
    m = bpy.data.materials.new("skym")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = -10
    mr.inputs["From Max"].default_value = 70
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (1.0, 0.93, 0.8, 1)
    ramp.color_ramp.elements[1].color = (0.25, 0.6, 1.0, 1)
    em = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(tc.outputs["Object"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    o.data.materials.append(m)


def build_lights():
    sc = bpy.context.scene

    def light(name, kind, energy, loc, rot, color=(1, 1, 1), size=None):
        d = bpy.data.lights.new(name, kind)
        d.energy = energy
        d.color = color
        if size is not None:
            d.size = size
        o = bpy.data.objects.new(name, d)
        sc.collection.objects.link(o)
        o.location, o.rotation_euler = loc, rot
        return o

    light("sun", "SUN", 4.2, (0, 0, 10), (math.radians(48), math.radians(8), math.radians(-28)), (1.0, 0.94, 0.82))
    light("fill", "AREA", 200, (-4, -6, 3.5), (math.radians(75), 0, math.radians(-30)), (0.95, 0.95, 1.0), size=6)
    light("rim", "AREA", 140, (3, 6, 4), (math.radians(-110), 0, math.radians(160)), (1.0, 0.85, 0.7), size=4)
    w = bpy.data.worlds.new("w")
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (1.0, 0.96, 0.88, 1)
    bg.inputs["Strength"].default_value = 0.45
    sc.world = w


# ----------------------------------------------------------------- camera
def camera_track(kind, N, fps, centers, lead_root):
    sc = bpy.context.scene
    cd = bpy.data.cameras.new("cam")
    cd.lens = 38
    co = bpy.data.objects.new("cam", cd)
    sc.collection.objects.link(co)
    sc.camera = co
    tgt = empty("camtarget")
    tr = co.constraints.new("TRACK_TO")
    tr.target, tr.track_axis, tr.up_axis = tgt, "TRACK_NEGATIVE_Z", "UP_Y"
    cd.dof.use_dof = True
    cd.dof.focus_object = lead_root
    cd.dof.aperture_fstop = 3.5
    k = (kind or "").lower()
    dist, elev, az = 6.2, 1.5, 0.0
    if "wide" in k:
        dist = 8.0
    if "low angle" in k:
        elev, dist = 0.15, 5.5
    smooth = [0.0, 0.0, 0.0]
    for f in range(N):
        u = f / max(1, N - 1)
        c = centers[f]
        for i in range(3):
            smooth[i] = lerp(smooth[i], c[i], 0.12) if f else c[i]
        d, e, a = dist, elev, az
        tx, ty, tz = smooth[0], smooth[1], smooth[2] + 0.85
        if "push" in k:
            d = dist * lerp(1.0, 0.72, ease(u))
        if "orbit" in k:
            a = lerp(-0.4, 0.4, u)
        if "crane" in k or "upward" in k:
            e = lerp(0.6, 3.2, u)
        if "pan" in k:
            a = lerp(-0.15, 0.2, u)
        if "low angle" in k:
            tz = smooth[2] + lerp(1.0, 3.2, ease(u))
        if "tracking" in k or "fast" in k:
            d = dist * 0.85
        co.location = (tx + d * math.sin(a), ty - d * math.cos(a), e + (smooth[2] * 0.6 if "crane" not in k else smooth[2] * 0.8))
        tgt.location = (tx, ty, tz)
        co.keyframe_insert("location", frame=f + 1)
        tgt.keyframe_insert("location", frame=f + 1)
    return co


# ----------------------------------------------------------------- render
def setup_render(spec):
    sc = bpy.context.scene
    r = sc.render
    r.resolution_x, r.resolution_y = spec["res"]
    r.resolution_percentage = 100
    r.fps = spec["fps"]
    r.image_settings.file_format = "PNG"
    sc.frame_start, sc.frame_end = 1, spec["frames"]
    eng = spec.get("engine", "eevee")
    if eng == "cycles":
        r.engine = "CYCLES"
        sc.cycles.samples = spec.get("samples", 24)
        sc.cycles.device = "CPU"
        try:
            sc.cycles.use_denoising = True
        except Exception:
            pass
    elif eng == "workbench":
        r.engine = "BLENDER_WORKBENCH"
        sc.display.shading.light = "STUDIO"
        sc.display.shading.color_type = "MATERIAL"
    else:
        for name in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE_LEGACY"):
            try:
                r.engine = name
                break
            except TypeError:
                continue
        try:
            sc.eevee.taa_render_samples = spec.get("samples", 32)
        except Exception:
            pass
    try:
        sc.view_settings.view_transform = "Standard"
        sc.view_settings.look = "None"
    except Exception:
        pass


def main(spec):
    sc = bpy.context.scene
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    try:
        bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
    except Exception:
        pass
    rng = random.Random(spec.get("seed", 1))
    setup_render(spec)
    build_sky()
    build_env(spec["scene"], rng, spec["motion"], spec.get("backdrop", ""))
    build_lights()
    chars = spec["characters"]
    kids, allposes = [], []
    lead_idx = next((i for i, c in enumerate(chars) if c["role"] == "lead"), 0)
    # lead first so the supporting cast can look at it
    order = [lead_idx] + [i for i in range(len(chars)) if i != lead_idx]
    lead_pos = None
    for i in order:
        c = chars[i]
        k = Kid(c["name"], c["species"])
        poses = make_poses(k, c["role"], i, len(chars), spec, rng, lead_pos if c["role"] != "lead" else None)
        if c["role"] == "lead":
            lead_pos = (poses[len(poses) // 2]["x"], poses[len(poses) // 2]["y"])
        kids.append(k)
        allposes.append(poses)
    N = spec["frames"]
    for k, poses in zip(kids, allposes):
        for f, p in enumerate(poses):
            k.pose(p, f + 1)
    centers = []
    for f in range(N):
        xs = [ps[f]["x"] for ps in allposes]
        ys = [ps[f]["y"] for ps in allposes]
        zs = [ps[f]["z"] for ps in allposes]
        lead = allposes[0][f]
        w = 0.7 if len(allposes) > 1 else 1.0
        centers.append((lerp(sum(xs) / len(xs), lead["x"], w - 0.5 if len(allposes) > 1 else 0.0),
                        sum(ys) / len(ys), max(zs) * 0.8))
    camera_track(spec.get("camera", ""), N, spec["fps"], centers, kids[0].root)
    out = spec["out_dir"]
    os.makedirs(out, exist_ok=True)
    still = spec.get("still")
    if still:
        sc.frame_set(int(still))
        sc.render.filepath = os.path.join(out, "still.png")
        bpy.ops.render.render(write_still=True)
        return
    rng_f = spec.get("frame_range")
    if rng_f:
        sc.frame_start, sc.frame_end = int(rng_f[0]), int(rng_f[1])
    sc.render.filepath = os.path.join(out, "f_")
    bpy.ops.render.render(animation=True)


def run_from_argv():
    argv = sys.argv
    spec_path = argv[argv.index("--") + 1]
    with open(spec_path, encoding="utf-8") as fh:
        main(json.load(fh))
