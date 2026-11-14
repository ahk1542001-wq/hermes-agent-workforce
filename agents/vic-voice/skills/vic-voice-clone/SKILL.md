---
name: vic-voice-clone
description: Produce VIC Burmese cloned narration on the existing Colab/VoxCPM route, for standalone audio or Creator video jobs, with measured chunk timing and recovery.
---

# VIC shared voice procedure

This is the single voice procedure for standalone Voice and direct Creator execution. The caller owns the exact current job, scripts, session and output directory; no bot handoff is required. Load only this procedure and [CLI execution](references/cli-execution.md) when synthesizing. Do not load old pilot/training notes for routine narration. Do not change providers, install software on the Mac, train a model or use local GPU to resolve an ordinary generation failure. Preparing the existing VoxCPM dependencies/model inside an owned disposable Colab runtime is a separate scoped setup step; follow CLI execution authorization below.

## Freeze and chunk approved speech

Use the genuine owner-approved reference and record its hash; an existing confirmation remains valid for the same recording. Current retained reference is `/opt/vic/profiles-root/profiles/vic-voice/attachments/Voice victor.m4a`; verify against the current approved receipt, not filename alone. Silence statistics can flag trouble but cannot prove whether a recording is genuine. Do not invent its transcript. Reference-only conditioning needs no prompt transcript; exact owner-confirmed words are required before any prompt-conditioning experiment.

Keep two text fields: `visible_text` preserves approved display/caption wording; `spoken_text` records pronunciation substitutions without changing meaning. VIC is spoken `ဗစ်`; AI is spoken `အေအိုင်` when needed. Log any other substitution; never silently rewrite the approved script.

Create `chunks.json`, an ordered list of `{id, visible_text, spoken_text, est_s, max_patches, pause_ms}`. IDs are unique safe basenames. Start with natural short sentences/clauses; break at punctuation or a verified Burmese syllable/phrase boundary, never through a combining sequence or protected English term. Merge tiny trailing fragments. The prior 'every chunk <4s' rule conflicts with the actual 6.75–9.42s estimates in the retained RAG/Memory jobs; it is not a universal limit. Use manageable phrase lengths, then split a specific chunk if its actual output truncates, repeats or drifts. Estimates and max_len are guardrails, not evidence of complete speech.

Choose pauses for the intended delivery and store them explicitly per chunk. Continuing phrases normally need no extra wait; sentence ends may need a short natural breath. Prior jobs used different pause budgets: neither 160ms everywhere nor 450ms everywhere is mandatory. Do not pad speech to an invented storyboard duration or speed it to fit; derive visual timing from measured narration. Extra target silence, if explicitly needed, must be identified in the receipt. No compulsory music/SFX for a voice-only request.

## Generate on existing Colab route

Check scoped upload permission for this script/reference; reuse existing permission only for its actual scope. Use the installed OAuth2 Colab CLI, unset PYTHONPATH, and inspect ownership before allocating. No Vertex voice inference, ADC switch, paid compute or browser fallback. Download weights/warm up separately when needed. Keep the genuine speech-ending reference trim; decode AAC to PCM WAV if the selected decoder requires it, without modifying the original.

Use [scripts/synthesize.py](scripts/synthesize.py) on the GPU with current-job arguments. It is an extracted, parameterized version of the retained VoxCPM2 reference-only recipe: `cfg_value=2.0`, `inference_timesteps=10`, no chain from preceding synthetic chunks. These are current working defaults, not universal quality claims. A retry that is merely longer or byte-identical is not a repair. Inspect coverage/listen and repair at most twice per concrete defect; fail rather than silently accepting BEST_EFFORT. Short-duration screening cannot detect wrong words or missing clauses.

One session/output owner at a time. Use the shared [scripts/driver.py](scripts/driver.py) for job preparation, Colab execution, retrieval and assembly; bots supply job inputs rather than writing another driver. Run its staged job snapshot as a tracked detached process for long work, with durable log and current input hashes. A local timeout does not mean the remote kernel stopped. Inspect remote chunk/receipt progress first; never immediately repeat synthesis or terminate a possibly successful run. Download and verify all expected IDs and hashes before stopping only the owned runtime. See the CLI reference for exact execution/recovery contract.

## Finish and measure

Preserve raw chunks. [scripts/assemble.py](scripts/assemble.py) writes a fresh output directory, 48kHz mono PCM16 master, exact sample-based chunk timing, 10ms narration-only envelope and SHA receipt. It refuses partial/mismatched inputs and existing outputs. It applies small 10ms head/20ms tail raised-cosine fades, explicit per-chunk pauses, no automatic pitch/rate/EQ/loudness changes. These fades do not remove long silence or verify pronunciation.

Inspect excessive chunk-edge silence and breaths before choosing a trim; do not clip phonemes or reuse the historical English-gap cutter across Burmese consonants. If trimming/crossfading is needed, do it in a new processed-chunk directory, record it, then measure timing again. Do not apply the historical 150ms crossfade or pitch normalization to every clip. Report silence/peak/loudness and tune only a demonstrated defect. Never synthesize fake breaths. Do not normalize near-silent material (RMS <1e-4).

Before delivery: verify all approved text is spoken, no repetition/truncation/chirp/click, joins are natural, correct protected terms, no clipping, and intended loudness. Sample counts/energy are mechanical checks, not voice identity or semantic acceptance. Report exactly what was listened to and who reviewed it; only Victor accepts the likeness. Return master/hash, sample rate/count/duration, per-chunk visible/spoken text/start/end/pause, model/parameters/reference and input hashes, raw/processed paths and actual listening limits. Envelope is amplitude animation, not phoneme alignment. Voice completion does not approve the video or publishing.
