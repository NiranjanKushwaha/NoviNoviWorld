# ComfyUI workflow for the GPU pod

`movie_studio.py render --provider manual` loads `workflows/i2v_api.json` (path set in studio_config.json).

1. On the pod, open ComfyUI, build/load an image-to-video workflow (LTX-Video or Wan 2.2) that works.
2. Menu -> Export (API) -> save as `workflows/i2v_api.json`.
3. In that JSON replace the values to be controlled with placeholders (whole-string placeholders keep int/float type):
   `{{image}}` start frame, `{{prompt}}`, `{{negative}}`, `{{seed}}`, `{{frames}}`, `{{width}}`, `{{height}}`,
   `{{fps}}`, `{{prefix}}` (output name), optional `{{audio}}`.
4. A leftover or unknown placeholder aborts before queueing, so mistakes cost nothing.
