# 🐰 NoviNovi World Studio (@NoviNoviWorld)
Automated 3D Kids Animation Video Production Engine for YouTube & Instagram

---

## 📁 Standardized Project Architecture

```
AntiGravity-video-generator/
├── .agents/skills/                    # Specialized Antigravity Skills
│   ├── novinovi-world-director/       # Creative director for characters & storytelling
│   ├── kids-video-generator/          # Automated FFmpeg assembly pipeline
│   ├── copyright-free-audio/          # Child voice tuning & zero-copyright sound design
│   └── video-reviewer-and-publisher/  # Automated mobile & broadcast compliance auditor
├── docs/                              # Official Brand & Animation Bibles
│   ├── CHARACTERS_AND_WORLD_BIBLE.md  # 3D Pixar character DNA & Wonder Forest universe
│   └── CHARACTER_ACTION_PHYSICS_BIBLE.md # Realistic physics prompts (climbing, dancing, sliding)
├── assets/                            # Master Project Assets
│   └── characters/                    # High-res 3D character reference artwork (Novi, Mimi, etc.)
├── src/                               # Modular Core Engine
│   ├── voice_engine.py                # Sweet, authentic child voice generator (Edge-TTS)
│   ├── video_assembler.py             # Multi-platform 1080p video compiler (H.264/AAC)
│   ├── video_auditor.py               # Mobile playback & color space (yuv420p) auditor
│   └── higgsfield_api.py              # Higgsfield AI Python SDK video generation helper
├── episodes/                          # Episode Production Directories
│   └── ep01_rainbow_slide/            # Episode 1: The Magic Tree Climbing & Rainbow Slide
│       ├── audio/                     # Child voice dialogues (Hindi & English)
│       ├── clips/                     # Moving 3D video clips from Higgsfield AI / Kling
│       └── exports/                   # Verified ready-to-upload YouTube & Instagram MP4s
├── studio.py                          # Unified CLI Entry Point
├── requirements.txt                   # Project dependencies
└── README.md                          # Master documentation
```

---

## 🚀 Studio CLI Commands

Activate your virtual environment:
```bash
source .venv/bin/activate
```

### 1. Generate Adorable Child Voices (Hindi or English)
```bash
# Generate sweet Hindi child voices (Novi, Mimi, Pip, Toby):
python3 studio.py voices --lang hindi

# Generate English child voices:
python3 studio.py voices --lang english
```

### 2. Assemble Full Multi-Platform Videos
```bash
# Assembles YouTube Widescreen (1920x1080) & Instagram Reel (1080x1920):
python3 studio.py assemble --lang hindi
```

### 3. Review & Audit Exported Video Quality
```bash
python3 studio.py audit
```

### 4. Full Production Package in One Command
```bash
python3 studio.py package
```

---

## 🏃‍♂️ Generating Moving 3D Action Clips (Higgsfield AI & Kling AI)

To ensure characters **physically move, walk, dance, climb trees, and slide**:
1. Check [docs/CHARACTER_ACTION_PHYSICS_BIBLE.md](docs/CHARACTER_ACTION_PHYSICS_BIBLE.md) for the exact motion prompt for each scene.
2. In **Higgsfield AI** (`higgsfield.ai`), select **Image-to-Video**, upload the character image from `assets/characters/`, paste the prompt, and export the 1080p MP4 clip.
3. Drop the downloaded `.mp4` clips into `episodes/ep01_rainbow_slide/clips/` and run `python3 studio.py assemble --lang hindi`!
