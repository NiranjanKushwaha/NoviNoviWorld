"""
Higgsfield AI Video Generation Helper
Automates 3D character motion generation via Higgsfield Python SDK (higgsfield-client).
"""

import os
import sys

def generate_higgsfield_video(image_path: str, motion_prompt: str, output_clip_path: str, duration: int = 5):
    """
    Submits an Image-to-Video generation request to Higgsfield AI.
    Requires HF_KEY environment variable (key_id:key_secret).
    """
    hf_key = os.environ.get("HF_KEY")
    if not hf_key:
        print("\n⚠️ [Higgsfield API Notice]:")
        print("To generate moving AI video clips directly via Higgsfield API, set your API key:")
        print("  export HF_KEY=\"your_key_id:your_key_secret\"")
        print(f"Motion prompt prepared for manual generation in web console (higgsfield.ai):\n  \"{motion_prompt}\"")
        return None

    try:
        import higgsfield_client
        print(f"🚀 Submitting generation to Higgsfield AI: {os.path.basename(image_path)}...")
        model_id = "bytedance/seedance-2.5/image-to-video"

        # Upload image and submit
        result = higgsfield_client.subscribe(
            model_id,
            arguments={
                "prompt": motion_prompt,
                "image_url": image_path,
                "duration": duration,
                "resolution": "1080p"
            }
        )
        video_url = result.get("videos", [{}])[0].get("url") or result.get("url")
        print(f"✅ Generated Higgsfield Video: {video_url}")
        return video_url
    except Exception as e:
        print(f"❌ Higgsfield generation error: {e}")
        return None
