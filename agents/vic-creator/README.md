# VIC Creator

A single Hermes orchestrator with bounded execution workers. The main model owns audience, useful AI-agent use case, facts, narration, storyboard, visual metaphor, pacing, sound direction and final correction. A worker receives explicit inputs, expected outputs, allowed files and verification; it does not invent the creative plan. Independent work can run in parallel when useful, with one writer per output and one integrator.

## Five styles in one skill

| Style | Format default | Main treatment |
|---|---|---|
| vic-sh-uiMotion | 9:16 | Screens, UI and causal object animation |
| vic-sh-visualStory | 9:16 | Fresh cartoon situations and animated illustrations |
| vic-lg-spatialMotion | 16:9 | Layered objects, depth and motivated camera |
| vic-lg-cartoonStory | 16:9 | Cartoon acting, reactions and causal props |
| vic-lg-paperMotion | 16:9 | Paper/sticker scenes and kinetic chapters |

Duration follows explanation and measured speech. Characters, setting, palette and music follow the topic. The examples are evidence, not a fixed scene template.

## Workflow

Brief and source evidence → main's script/storyboard → owner approval → shared Voice sample/listening approval → measured narration → asset and scene execution packets → real-audio proof → owner approval → full render → main's encoded visual/audio review and fixes → owner final acceptance. Publishing is separate.

Read [the skill](skills/vic-video/SKILL.md), [runtime map](skills/vic-video/references/runtime-map.md), [setup](../../docs/VIDEO_SETUP.md) and [sample gallery](../../docs/VIDEO_SAMPLES.md).

## Included code

`resources/short/scripts`: job preparation, visual-plan validation, causal animation operations, presenter layout checks, sound plan/mix binding, frame export and encoded-file checks. `scripts/paper_timing.py` maps the shared measured narration into the paper engine's timing schema. Cartoon adapters bind narration and implement camera/rig extensions. The original third-party long-form engines and personal artwork are prerequisites, not silently bundled.

For short rendering, configure `VIC_FFMPEG`, `VIC_FFPROBE` if not on PATH and optionally `VIC_CHROME` for an existing Chrome binary. Playwright must be installed in your chosen environment. Supply Noto Sans Myanmar locally. Register your five approved PNG presenter poses with `python3 scripts/configure_presenter.py --poses YOUR_POSES_DIR --manifest /ABS/INSTALLED/skills/vic-video/resources/short/templates/presenter-assets.json`; this checks PNG headers and records hashes without copying personal files into Git. Then author job-local inputs according to `prepare_job.py`/`visual_contract.py`, run `prepare_job.py --job JOB`, `render_job.py --help` and `check_job.py --help`. These commands are not a one-click generator from an arbitrary topic.

Technical checks do not establish speech coverage, likeness or artistic acceptance. Preserve exact successful inputs and frozen outputs; inspect checkpoints before resuming.
