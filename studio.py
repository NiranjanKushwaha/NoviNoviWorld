#!/usr/bin/env python3
"""
NoviNovi World Studio CLI
Unified orchestrator for @NoviNoviWorld YouTube and Instagram video production.

Usage:
  python3 studio.py voices       # Generate authentic Hindi & English child character voices
  python3 studio.py assemble     # Assemble 1080p YouTube (16:9) & Instagram Reel (9:16) videos
  python3 studio.py audit        # Review exported video files for broadcast compliance
  python3 studio.py package      # Generate the complete episode storyboard, prompts, and SEO
"""

import os
import sys
import argparse
import asyncio
import glob

# Ensure src/ is importable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from src.voice_engine import generate_episode_audio, CHILD_VOICES
from src.video_assembler import assemble_final_video
from src.video_auditor import audit_video_file

EP01_DIR = os.path.join(BASE_DIR, "episodes", "ep01_rainbow_slide")
AUDIO_DIR = os.path.join(EP01_DIR, "audio")
CLIPS_DIR = os.path.join(EP01_DIR, "clips")
EXPORTS_DIR = os.path.join(EP01_DIR, "exports")
CHARACTERS_DIR = os.path.join(BASE_DIR, "assets", "characters")

# 8 Cinematic Scenes with Authentic Child Dialogues
EPISODE_SCENES = [
    {
        "scene": 1,
        "speaker": "Novi",
        "action": "Running & Hopping across forest path, smelling glowing flowers",
        "hindi": "Good morning Wonder Forest! Wah, kitni pyari subah hai! Chalo dosto, aaj ped pe chadhenge aur khoob masti karenge! Hop, hop, hooray!",
        "english": "Good morning Wonder Forest! What a beautiful sunny day! Come on friends, let's climb the big tree and have so much fun! Hop, hop, hooray!"
    },
    {
        "scene": 2,
        "speaker": "Mimi",
        "action": "Chubby Bear Belly Dance & Berry Munching",
        "hindi": "Haha! Novi dekho mera berry dance! Pet ko hilaao, gol gol ghoom jaao! Yummy berries in my tummy!",
        "english": "Haha! Novi look at my berry dance! Wiggle your tummy, spin all around! Yummy berries in my tummy!"
    },
    {
        "scene": 3,
        "speaker": "Pip",
        "action": "Fast Bird Flying & Pointing to High Canopy",
        "hindi": "Chirp chirp! Ooper dekho, ooper dekho! Sabse unchi daali par chamakta hua Golden Star-Fruit hai!",
        "english": "Chirp chirp! Look up high, look up high! The glowing Golden Star-Fruit is at the very top branch!"
    },
    {
        "scene": 4,
        "speaker": "Toby",
        "action": "Wise Turtle Stepping Stones & Encouragement",
        "hindi": "Dheere dheere Novi, ghabrana mat! Ek ek kadam aage badhao, tum pakka ped par chadh jaoge!",
        "english": "Slow and steady Novi, don't worry! Take it step by step, you can climb all the way up!"
    },
    {
        "scene": 5,
        "speaker": "Novi",
        "action": "Tree Climbing Physics: Paws gripping bark, pulling body upwards",
        "hindi": "Main chadhta hoon! Mazbooti se daali pakdi, ek haath ooper, ek paanv ooper! Yay, main kitna ooper aa gaya!",
        "english": "Here I go! Holding the branch tight, one paw up, one foot up! Yay, look how high I've climbed!"
    },
    {
        "scene": 6,
        "speaker": "Novi",
        "action": "Treehouse Balcony Victory Dance with High-Fives",
        "hindi": "Hurray! Main ped ke sabse ooper treehouse me hoon! Chalo sab milkar naacho! Bunny hop dance, left shake, right shake!",
        "english": "Hurray! I made it to the treetop treehouse! Let's all dance together! Bunny hop dance, shake left, shake right!"
    },
    {
        "scene": 7,
        "speaker": "Novi",
        "action": "Fast Spiral Rainbow Water Slide Zoom & Water Splash",
        "hindi": "Aur ab niche aane ka time! Rainbow slide par jump! One, Two, Three... WHOOOOOSH! Ye kitna thrilling hai!",
        "english": "And now it's time to slide down! Ready for the rainbow slide! One, Two, Three... WHOOOOOSH! This is so fast and fun!"
    },
    {
        "scene": 8,
        "speaker": "Mimi",
        "action": "Soft Marshmallow Landing, Sharing Fruit & Hugging",
        "hindi": "Boing! Novi tumne kar dikhaya! Aadha fruit tumhara, aadha mera! Sharing makes us best friends forever!",
        "english": "Boing! You did it Novi! Half for you, and half for me! Sharing makes us best friends forever!"
    }
]

def cmd_voices(lang: str = "hindi"):
    target_dir = os.path.join(AUDIO_DIR, lang)
    asyncio.run(generate_episode_audio(EPISODE_SCENES, lang, target_dir))

def cmd_assemble(lang: str = "hindi"):
    audio_track = os.path.join(AUDIO_DIR, lang, f"master_{lang}_soundtrack.mp3")
    if not os.path.exists(audio_track):
        print(f"Generating missing {lang} child audio track first...")
        cmd_voices(lang)

    # Use video clips if available, else master 3D assets
    clips = sorted(glob.glob(os.path.join(CLIPS_DIR, "*.mp4")))
    if not clips:
        clips = sorted(glob.glob(os.path.join(CHARACTERS_DIR, "*.jpg")))

    yt_out = os.path.join(EXPORTS_DIR, f"NoviNoviWorld_Ep01_YouTube_1080p_{lang}.mp4")
    ig_out = os.path.join(EXPORTS_DIR, f"NoviNoviWorld_Ep01_InstagramReel_9x16_{lang}.mp4")

    print(f"\n🎬 Assembling YouTube 16:9 Video ({lang})...")
    assemble_final_video(clips, audio_track, yt_out, is_vertical=False, clip_duration=6.0)
    print(f"✅ Exported: {yt_out}")

    print(f"\n📱 Assembling Instagram Reel 9:16 Video ({lang})...")
    assemble_final_video(clips, audio_track, ig_out, is_vertical=True, clip_duration=6.0)
    print(f"✅ Exported: {ig_out}")

def cmd_audit():
    exports = glob.glob(os.path.join(EXPORTS_DIR, "*.mp4"))
    print("\n=======================================================")
    print("🔍 AUDITING EXPORTED VIDEO FILES")
    print("=======================================================")
    for v in exports:
        rep = audit_video_file(v)
        status_icon = "✅" if rep["status"] == "PASS" else "❌"
        print(f"{status_icon} {rep['file']} | Res: {rep['resolution']} | Dur: {rep['duration']}s | Status: {rep['status']}")
    print("=======================================================\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NoviNovi World Studio CLI")
    parser.add_argument("command", choices=["voices", "assemble", "audit", "package"], help="Action to run")
    parser.add_argument("--lang", default="hindi", choices=["hindi", "english"], help="Language (default: hindi)")
    args = parser.parse_args()

    if args.command == "voices":
        cmd_voices(args.lang)
    elif args.command == "assemble":
        cmd_assemble(args.lang)
    elif args.command == "audit":
        cmd_audit()
    elif args.command == "package":
        cmd_voices("hindi")
        cmd_voices("english")
        cmd_assemble("hindi")
        cmd_audit()
