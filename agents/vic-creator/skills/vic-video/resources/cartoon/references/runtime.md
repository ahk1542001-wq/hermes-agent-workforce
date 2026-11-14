# Installed cartoon runtime

Canonical runtime: /opt/vic/runtimes/vic-cartoon-explainer. Pinned local dependencies were copied from the reviewed proof engine, not downloaded. package-lock.json is retained. Do not upgrade the engine or packages while producing a film.

The accepted file-sort movie is a frozen regression fixture (`vicFileSortFilm`), not a new-topic template. Preserve its source modules. For a new topic create separate canvas-core film/sound/narration modules and a matching hosts/page-NAME.ts; keep outputs in a fresh job directory. Main supplies creative decisions; execution tasks are bounded.

Run from the canonical runtime:

```sh
node tools/build-page.mjs FILM_NAME
node tools/render.mjs FILM_NAME --scale 1.5 --out /ABSOLUTE/NEW/JOB/proof.mp4
node tools/verify-export.mjs FILM_NAME --file /ABSOLUTE/NEW/JOB/proof.mp4 --scale 1.5 --fidelity-psnr 35 --delivery
```

The canvas base is 1280x720; scale1.5 gives1920x1080,30fps. A different aspect ratio requires an explicit new composition and bounds review, not scaling this horizontal layout. The cartoon runtime is separate from KAPE spatial landscape and the two vertical ShortForm treatments. Owner selects the style.

Use the bundled rig in assets/runtime; preserve original VIC image identity. Existing reference images live in assets/vic and assets/vic-generated. Fictional supporting characters, environments and actions are chosen for the topic; do not reuse the file-sort cast or its melody by default.

Bind authorized shared-voice outputs with scripts/bind_narration.py from this skill directory. --separate-stems requires the job sound module to export makeMusic and makeEffects; both return stereo arrays. Design times are measured storyboard boundaries, not mandatory music BPM. This binding script does not synthesize speech or authorize uploads. Keep narration dry for mouth amplitude.

Technical verification and native skill discovery do not certify unattended Hermes production, listening or owner creative acceptance. Use the exact encoded representative proof gate for a new topic.
