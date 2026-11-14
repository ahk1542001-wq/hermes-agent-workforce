# Creator and Voice setup

## What you need

- A separately installed Hermes host with the tools you explicitly enable: terminal/file access; browser or screenshot tools for authentic product evidence; image generation only when configured and authorized.
- A main reasoning model for creative planning/review. An independently configured execution model can implement bounded packets. The owner-local design used a larger main model and Gemini Flash workers through 9Router. These are roles, not mandatory provider IDs; use models actually available in your account. A ChatGPT subscription is not a general API credential.
- Python 3.11+, NumPy and FFmpeg/FFprobe for local voice assembly and checks. Playwright/Chrome for the short renderer. Node and the selected upstream engines for long styles.
- An authenticated, compatible Colab CLI and authorized reference audio for cloud voice. GPU packages/model weights are installed only in an owned authorized disposable runtime.
- Your own licensed character poses, illustrations, local fonts, music and sound assets. Never use upstream demo mascots as personal branding.

## Install the two profile templates

```sh
python3 scripts/install_video_profiles.py --profiles-root /ABS/FRESH/PROFILES --runtime-root /ABS/RUNTIMES
# Review the printed destinations, then explicitly apply:
python3 scripts/install_video_profiles.py --profiles-root /ABS/FRESH/PROFILES --runtime-root /ABS/RUNTIMES --apply
```

The destination must be outside this source checkout. Neither profile may already exist. The installer copies SOUL instructions and skills, resolves the shared Voice path to the new profiles root and writes the chosen runtime-root references. It does not install Hermes, dependencies, engines, secrets, model configuration or native workers. Enable the profiles/skills in your installed Hermes version, configure models/tools through its supported settings, and start a fresh chat. Host-version compatibility needs local verification.

## Runtime layout

Place your reviewed runtime checkouts under the chosen root as `vic-content-studio`, `vic-cartoon-explainer`, `vic-landscape-explainer`. The public exported skill identifies the adapters and upstream engines; follow [runtime map](../agents/vic-creator/skills/vic-video/references/runtime-map.md). Legacy owner-job paths in historical examples are generalized under `/opt/vic/legacy`; they are examples, not files supplied here. Author fresh job inputs, never replay an old job launcher.

## Check safely first

```sh
python3 scripts/verify_video.py
```

This runs only synthetic/local tests and public-boundary checks. No network, image generation, TTS inference, account/GPU allocation or real reference upload. A successful check proves the exercised helpers and gates, not a new full video or cross-platform compatibility. Continue with the smallest authorized voice sample and representative real-audio visual proof before a full production job.

## Kept private

Never commit reference audio, job authorization receipts, OAuth tokens, API keys, service accounts, session databases, logs, personal browser captures, generated jobs or caches. Public demo narration already approved for the portfolio is distinct from the original cloning reference.
