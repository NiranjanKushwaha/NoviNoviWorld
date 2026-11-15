"""Blender entry point:  blender -b -P render_shot.py -- spec.json"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import studio3d  # noqa: E402

studio3d.run_from_argv()
