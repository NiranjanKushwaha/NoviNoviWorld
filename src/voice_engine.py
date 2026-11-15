"""
NoviNovi World: Authentic Child Voice Engine
Generates genuine, cute, and lovable child voices that toddlers and kids adore.
Uses high-pitch, expressive neural acoustic modeling (Microsoft Edge-TTS).
"""

import os
import sys
import asyncio
import edge_tts
import subprocess

# Cute, Playful Child Voice Profiles
CHILD_VOICES = {
    "Novi": {
        "desc": "Playful, energetic 4-year-old baby bunny (Main Hero)",
        "hindi": {"voice": "hi-IN-SwaraNeural", "pitch": "+35Hz", "rate": "+12%"},
        "english": {"voice": "en-US-AnaNeural", "pitch": "+10Hz", "rate": "+10%"}
    },
    "Mimi": {
        "desc": "Chubby, sweet, giggly bear cub",
        "hindi": {"voice": "hi-IN-MadhurNeural", "pitch": "+28Hz", "rate": "+8%"},
        "english": {"voice": "en-US-AndrewNeural", "pitch": "+8Hz", "rate": "+8%"}
    },
    "Pip": {
        "desc": "Tiny, fast-talking, chirpy baby bluebird",
        "hindi": {"voice": "hi-IN-SwaraNeural", "pitch": "+45Hz", "rate": "+20%"},
        "english": {"voice": "en-US-AnaNeural", "pitch": "+18Hz", "rate": "+22%"}
    },
    "Toby": {
        "desc": "Calm, gentle, sweet-mannered baby turtle",
        "hindi": {"voice": "hi-IN-MadhurNeural", "pitch": "+10Hz", "rate": "-6%"},
        "english": {"voice": "en-US-BrianNeural", "pitch": "+4Hz", "rate": "-5%"}
    }
}

async def generate_speech_clip(text: str, character: str, language: str, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cfg = CHILD_VOICES.get(character, CHILD_VOICES["Novi"])[language]
    comm = edge_tts.Communicate(text, cfg["voice"], rate=cfg["rate"], pitch=cfg["pitch"])
    await comm.save(output_path)
    return output_path

async def generate_episode_audio(scenes_data: list, language: str, output_dir: str):
    """
    Renders all scene character dialogues and merges into a master episode soundtrack.
    """
    os.makedirs(output_dir, exist_ok=True)
    audio_clips = []

    print(f"\n🎙️ Generating {language.upper()} Child Dialogue Track...")
    for sc in scenes_data:
        char = sc["speaker"]
        text = sc[language]
        clip_file = os.path.join(output_dir, f"scene_{sc['scene']:02d}_{char.lower()}.mp3")
        await generate_speech_clip(text, char, language, clip_file)
        audio_clips.append(clip_file)
        print(f"  👶 [{char} ({language})]: \"{text[:40]}...\" -> {os.path.basename(clip_file)}")

    # Concat file list
    concat_txt = os.path.join(output_dir, "concat.txt")
    with open(concat_txt, "w") as f:
        for a in audio_clips:
            f.write(f"file '{os.path.abspath(a)}'\n")

    master_track = os.path.join(output_dir, f"master_{language}_soundtrack.mp3")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_txt, "-c", "copy", master_track
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    print(f"🎉 [Master Soundtrack Ready]: {master_track}")
    return master_track

if __name__ == "__main__":
    test_phrase = "Good morning friends! I am Novi the Bunny! Let's play and have fun!"
    asyncio.run(generate_speech_clip(test_phrase, "Novi", "english", "output/test_voice.mp3"))
