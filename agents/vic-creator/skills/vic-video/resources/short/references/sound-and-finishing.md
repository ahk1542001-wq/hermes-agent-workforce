# Sound design, narration and final mix

Main orchestrator sets the intended sound treatment and reviews it; Gemini Flash executes the frozen cue assets, event schedule, mix and repairs using the helper; creative sound planning remains with main. Standalone Voice remains dry narration. Video narration uses the shared voice procedure, with scoped private upload permission and one session/output owner. Never use music/SFX to drive mouth animation: keep the narration-only envelope unchanged unless speech changes.

## Plan sound with the shots

For each meaningful event decide sound or deliberate silence: object-contact/UI/foley cue, important transition/accent, background music/ambience. Store the shot/event connection, origin/license, purpose, time, duration and level in sound-plan.json/current job notes. Do not put a whoosh on every cut, bell on every label, or repeat the old film's cue schedule. Match this story's mood and pace. A narrated explainer follows measured speech; music follows it. Beat-driven montage may use a common beat grid. Never accelerate approved speech to fit a BPM.

Every new Short Form job must have an explicit sound plan and mix receipt before prepare. Default video treatment is designed music plus selective action/transition SFX; an omitted layer needs an explicit reason in the approved storyboard/proof. Voice-only is a deliberate owner/job choice, not a silent fallback when assets are missing. This rule is scoped to this Short Form skill; do not change a separate long-form or standalone pure-voice job.

Use job-local audio with real source/license metadata, or original locally synthesized assets with origin notes. The helper does not fetch or generate sound. Attribution text is not proof of license; do not invent it or borrow unreviewed old audio merely because a WAV exists. Do not upload reference voice to a music/image service, install packages or buy tracks/credits.

## Exact job-local plan

```
{
  "mode": "designed",
  "narration": "voice/narration.wav",
  "duration_s": 90,
  "target_lufs": -18,
  "true_peak_dbtp": -1.5,
  "music": [{"id":"bed_a","path":"sound/bed.wav","at_s":0,"duration_s":90,"loop":true,"gain_db":-24,"fade_in_s":0.5,"fade_out_s":1,"source":"actual origin","license":"actual usage rights","purpose":"quiet support for explanation"}],
  "sfx": [{"id":"object_arrival","path":"sound/tap.wav","at_s":8.2,"duration_s":0.2,"gain_db":-16,"source":"actual origin","license":"actual usage rights","purpose":"matches the object landing in shot_b"}]
}
```

These values are an example, not a fixed palette, tempo, event quota or universal mix setting. Empty music/sfx lists need music_omission_reason/sfx_omission_reason; mode voice-only requires both empty. Film duration must be30fps-aligned and cover every narration sample; cues and tails must fit it. Nonlooping cues must have enough actual audio. Keep fades short enough for their cue.

Calibrate with comparable units: active-cue RMS against local dry-voice RMS, measured after pan/fades in the same window; peak limits are ceilings, not RMS targets. Centered constant-power panning can add3dB of attenuation relative to a duplicated-mono voice. Measure the actual stereo result and quiet-voice pauses. Normalize source assets before deriving gains. If a stem is already ducked, use a verified mix path that does not duck it again; the stock helper normally applies music ducking. Do not assume an unsupported flag changes that behavior.

Run from the skill directory:
```
/Applications/Hermes\ Agent.app/Contents/Resources/agent-payload/venv/bin/python3 scripts/sound_mix.py --job /ABS/OWNED/JOB --plan sound-plan.json --output sound-mix.wav
```

It creates a separate premaster,48kHz stereo PCM24 mix and sound-mix.mix.json. It preserves narration/raw assets; schedules cues sample-aligned; ducks the music bus from narration with sidechain compression; mixes SFX separately; then measures and performs two-pass loudness mastering with explicit48kHz output. Defaults target−18LUFS/−1.5dBTP; select a suitable target and verify actual encoded output. Fade/gain/ducking require listening: fixed meters cannot judge masking or taste. The mix receipt remains MIXED_PENDING_LISTENING_REVIEW, not approval.

In job.json bind audio="sound-mix.wav", sound_plan="sound-plan.json", sound_receipt="sound-mix.mix.json" and envelope=the original dry-narration10ms envelope. Preserve original measured narration chunks; bind display text separately according to the selected mode in SKILL.md. Preparation validates the receipt and all dry voice/cue/plan/mix hashes; changing a source invalidates dependent build/review. A new mix version needs a new output name/revision, not overwriting the old approved file.

## Proof and final gates

The real-audio proof includes representative narration, BGM, SFX and a transition when relevant, not a dry placeholder. Check spoken words are clear, cues align with actual encoded action, no repeat/fatigue, loops/joins/fades click-free and endings intact. Inspect the encoded proof and final, not just a WAV. Technical QA checks decode, timeline/format and encoded loudness/peak against the bound plan; main records actual listening coverage and unresolved masking/sync issues. Sample-based or meter-only review never certifies the complete audible experience. Owner proof/final acceptance and publishing remain separate.
