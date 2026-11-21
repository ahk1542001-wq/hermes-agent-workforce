# v-vic · Commercial video with Hermes

Victor designed this workflow for human-directed product films. The owner sets the
brief and approves the story and takes. The Hermes main agent plans the film and
reviews the work. Scoped workers can help with shot research, asset checks and
local edit tasks. An operator manages authorized generation in Google Flow.
FFmpeg, Pillow and motion graphics tools handle finishing.

## Set up the profile

Use an existing Hermes installation and a new profile directory. Python 3 and
FFmpeg with libx264 and AAC support are required for the local example.

```sh
python3 scripts/install_video_profiles.py --profile v-vic \
  --profiles-root /absolute/path/to/profiles --runtime-root /absolute/path/to/runtimes --apply
```

Enable the copied profile and commercial-video skill in your Hermes installation.
Configure your main model, optional worker and local tools through the host.
The installer copies the profile and skill templates. Flow login, authorized
reference media and generation remain operator steps.

## Run the local example

```sh
sh agents/v-vic/examples/render-example.sh ./commercial-example
```

Two synthetic plates become a two-second vertical review MP4 with one continuous
audio track. The script checks frame count and decodes both streams. The two
source clips also remain available as clean inserts.

## Use it on a film

Follow the [commercial video skill](skills/commercial-video/SKILL.md).
Record the brief, shot IDs, source ranges, title and product artwork references,
audio plan and review notes. When lettering fails in a generated shot, track
approved artwork onto the product in post and check the repaired interval at
delivery size.

The owner-local Hermes pilot exercised local editing, rendering and review using
existing footage. The portfolio examples illustrate the wider human-directed
workflow, including supervised generation and hands-on finishing. This public
setup verifies the local example. Fresh generation and unattended production
require separate live validation.

[Commercial production case study](https://portfolioweb-three-sigma.vercel.app/work/v-vic)
