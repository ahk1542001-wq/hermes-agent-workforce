# VIC Voice — shared procedure, standalone agent

The same procedure and driver serve standalone narration and Creator videos. No duplicated voice backend or model training. VoxCPM2 conditions on an authorized reference recording; keep your reference outside this repository.

## Real implementation

- `skills/vic-voice-clone/scripts/driver.py`: offline preparation, input/permission hashes, owned T4 allocation, scoped bootstrap/upload, generation, retrieval and timeout recovery.
- `synthesize.py` and `remote_run.py`: per-chunk VoxCPM generation and durable remote status/archive.
- `assemble.py`: raw chunk preservation, explicit pauses, 48kHz master, exact sample timings, 10ms speech envelope and hashes.
- `deadline_runner.py`, `safe_diagnostics.py`: process deadlines and safe diagnostics.
- `test_driver.py`: offline integration fixtures, including sample/full flow, foreign-session refusal, changed-input rejection and unsafe archives.

## Setup and use

Read [the voice skill](skills/vic-voice-clone/SKILL.md) and [CLI procedure](skills/vic-voice-clone/references/cli-execution.md). Supply your existing authenticated OAuth2 Colab CLI; this package does not ship a Colab client or account login. Use its documented `exec -s SESSION -f FILE --timeout N`, upload/download, usage/sessions/new/stop interface. Another Colab CLI implementation is not assumed compatible.

1. Freeze approved narration and phrase-sized `chunks.json`; keep separate visible and spoken wording.
2. Obtain actual scoped permission for the current script, reference, GPU allocation and any runtime dependencies/model download. Hash-bound authorization files record permission; they cannot grant it.
3. Prepare an offline job: `python3 skills/vic-voice-clone/scripts/driver.py prepare --config /ABS/JOB/voice-config.json --work /ABS/JOB/run-01`.
4. Explicitly invoke `run --work /ABS/JOB/run-01 --colab /ABS/installed/colab`. It can allocate GPU/upload personal speech inputs: do this only with the correct authorization.
5. Inspect and listen to the sample. Full mode requires an actual owner sample-review receipt. On interruption use `status`/`recover`; do not blindly replay inference.
6. Retrieve/verify, stop only the owned runtime, assemble and review every spoken chunk/join. Return a candidate until the owner accepts likeness and coverage.

Free T4 availability is conditional. No paid compute purchase, local GPU fallback, provider switch, or new training is performed automatically. Original recordings and authentication are never included in the public release.

Offline tests: `python3 -m unittest discover -s skills/vic-voice-clone/scripts -p test_driver.py -v` (NumPy and FFmpeg required). Synthetic test audio is never production narration.
