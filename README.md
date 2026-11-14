# VIC Creator & Voice — Hermes Video Production

AI-assisted Burmese video production, directed by Victor. One Creator plans the story and coordinates bounded execution workers; a shared Voice procedure also runs independently.

**[Watch the portfolio](https://portfolioweb-three-sigma.vercel.app/films) · [Creator setup](agents/vic-creator/README.md) · [Voice setup](agents/vic-voice/README.md) · [Interview walkthrough](docs/VIDEO_PRODUCTION.md)**

| Package | Responsibility | Published implementation |
|---|---|---|
| [VIC Creator](agents/vic-creator) | Research synthesis, scripting, storyboard, creative direction, worker packets, final review | Five-style skill, browser renderer, visual contract, sound mixer, timing helpers and runtime adapters |
| [VIC Voice](agents/vic-voice) | Standalone or Creator narration | Shared Colab driver, VoxCPM synthesis, raw-chunk retrieval, assembly, measured timing, envelope and recovery tests |

This is a public-adapted export of an existing owner-local workflow, not a new agent framework. Hermes is the host. Original voice references, credentials, account configuration, conversations and project jobs are excluded. Renderers need your own authorized media/fonts and the documented upstream runtimes. The instructions and source are available; a fresh-machine, unattended five-style run is not certified.

## Start here

1. Read [setup and boundaries](docs/VIDEO_SETUP.md).
2. Configure two fresh Hermes profiles using [the profile installer](scripts/install_video_profiles.py); it refuses existing destinations and never configures authentication.
3. Read the Creator or Voice README; choose the corresponding skill.
4. Run `python3 scripts/verify_video.py` in an environment with NumPy and FFmpeg. Tests are offline and synthetic; they allocate no GPU and make no model calls.

## Attribution

Victor designed the workflow, creative constraints and review process and directed AI-assisted implementation. Hermes, VoxCPM, Huashu, AniDoodle, HyperFrames, GSAP, Playwright and FFmpeg are upstream tools, not original frameworks authored by Victor. See [video attribution](docs/VIDEO_ATTRIBUTION.md).
