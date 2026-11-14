# vic-lg-paperMotion — VIC paper motion

Runtime: `/opt/vic/runtimes/vic-content-studio/huashu-art-motion/scripts/engine`. This is the retained paper/sticker Canvas/JavaScript engine with a Python/Playwright capture and FFmpeg export, separate from the VIC spatial and cartoon runtimes. Existing MP4s establish historical local output, not fresh Hermes end-to-end qualification.

## Choose the craft for this lesson

Use classic paper scenes (`paper.js`, `vic.js`, scene Cues) for calm illustrated situations, or kinetic chapters (`kinetic.js`, KT helpers) when chapter-scale objects/typography/camera help explain a mechanism. Choose one API family per film. Do not require seven scenes, eleven chapters, fixed topics or3–6minutes. Scene count and duration follow the current long script and actual speech. Original local examples `demos/vic_vs_cloud` and `demos/vic_ai_token` show mechanics, not reusable narration/scene content.

Preserve the genuine VIC atlases/identity under the studio's owned `assets/vic-mini-v1/production-v25` and reviewed local scene helpers. The upstream MIT engine and font licenses do not grant production rights to restricted Huashu/third-party character/demo artwork. Read the studio's `docs/SECURITY_REVIEW.md`; use owned VIC assets rather than upstream showcase art.

## Shared voice, measured timing

Use the main entry's canonical shared Voice procedure and approved reference, chunking, pronunciation and Colab recipe. Do not load the legacy local skill's synthesis/assembly stages, run its job-specific voice drivers, force every phrase under4s/14–16syllables, delete natural pauses or treat pure-voice examples as a universal soundtrack rule. Existing film audio remains unchanged; a future explicit voice-only brief is honoured. Background treatment follows the current brief, with voice always clear.

After verified assembly, [paper_timing.py](../../scripts/paper_timing.py) converts the shared receipt plus its exact WAV into the engine timing schema. It verifies the WAV hash/format, IDs and sample intervals. Give it explicit chapter groups; it never changes audio or generates speech. Its scene intervals include inter-chunk pauses and final tail and cover the complete waveform. Do not compute era duration from last-word-end minus first-word-start when that drops a pause.

The existing `scripts/build_film_data.py` / `scripts/build_ai_token_data.py` are topic-bound generator examples. Make a fresh job-owned copy and adapt ROOT/WAV/TIMING/FILM_LIB/SCENES explicitly. Use the adapter's chapter intervals for ERAS durations, not the old generator's speech-only scene ends. Generate speech.js/timing.js/frames.js from the current job; retain exact sample timing/provenance. Do not overwrite the exemplar's files or its generator constants.

Chapter groups are an ordered JSON list of `{id, first, last}` objects (1-based inclusive chunk indices), supplied by main and covering every chunk exactly once. Example command, substituting the owned job's paths:

```sh
python /opt/vic/profiles-root/profiles/vic-creator/skills/vic-video/scripts/paper_timing.py --receipt /JOB/voice/assembled/receipt.json --voice /JOB/voice/assembled/narration.wav --groups /JOB/chapters.json --out /JOB/narration_timing.json
```

Generate the mouth envelope from dry narration. A final music/effects mix may be passed to the renderer only after checking that it preserves the same complete narration timeline/sample coverage.

## Author and export

A new authorised film gets a fresh `demos/<slug>` with own scenes/eras and output directory. Rewrite topic-specific scene code; reuse only reviewed generic helpers and owned assets. Register `SCENES.id.draw(c,lt,t)` and use absolute film time for chunk-cued actions. For classic scenes use Cues; kinetic scenes use KT chunk lookup/measurement/camera helpers and the generated chunk n field. Keep variables used by camera push lists in the correct scope. Avoid extreme fillZoom (maxZoom<=12 in this engine) and preserve the softened VIC pose-pop/settle values in the existing rig.

Measure real Myanmar glyphs with the selected font and fit labels around icons. Keep content above the caption band (current1080p composition: content<=910, captions around920+), preserve presenter clearance and object contact. No blank cuts, duplicate objects, paragraph-only staging or idle movement as the entire explanation. A different aspect/layout requires a verified composition change, not a resize.

Verify an already-installed interpreter/Playwright/FFmpeg before any production command. Do not use `uv run --with` to silently download dependencies or a browser/model. Missing dependencies are a concrete capability gap. From the engine, existing render.py supports --film, --audio, --fps30 and --out; inspect --help before adapting a new job. Existing qa.py needs an absolute --project engine path; film_gate.py checks the encoded movie. Syntax/text/bounds/transition checks, actual mechanism/cut/face samples, full decode/count/audio transport/loudness and honest listening limits still apply. Engine gates are not creative acceptance. Shared script/proof/owner/publication gates apply; this skill-only integration does not authorise production.
