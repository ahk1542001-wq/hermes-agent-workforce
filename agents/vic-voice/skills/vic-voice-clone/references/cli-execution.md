# Shared Colab voice driver

All bots use `scripts/driver.py` with the same synthesis and assembly helpers. Do not write a new job driver or execute an archived job's hardcoded launcher. Chunking remains in SKILL.md; this driver never writes narration or rechunks it. No model routing or credentials are embedded in the code.

## Inputs and permissions

Create a job-local JSON config with existing absolute paths:

```json
{
  "job_id": "example-job",
  "session": "example-voice-01",
  "mode": "sample",
  "chunks": "/ABS/JOB/chunks.json",
  "narration": "/ABS/JOB/narration-approved.txt",
  "reference": "/ABS/APPROVED/reference.m4a",
  "authorization": "/ABS/JOB/voice-authorization.json",
  "sample_ids": ["chunk_01"]
}
```

The authorization record must attest actual owner permission, never manufacture it. Required fields: matching `job_id`, `narration_sha256`, `reference_sha256`, `chunks_sha256`, and explicit booleans `upload_authorized`, `synthesis_authorized`, `allocation_authorized`, `model_download_authorized`. Set `remote_bootstrap_authorized` only when disposable-runtime dependency installation was actually approved. Existing permission counts for its original job scope after a runtime restart; it does not authorize other jobs, paid compute purchases, Mac installations or another provider. Normalize older owner receipts into this small record while preserving their source/meaning; adding a boolean is not permission.

The reference, chunks, narration, authorization and helper hashes are bound at prepare. Visible chunk text must cover approved narration in order. Code snapshots live in the work directory so another bot resumes the same exact implementation. A different script, reference or changed helper requires a fresh work revision; accepted outputs are never overwritten.

## Commands

Use the existing Hermes Python environment (numpy available for assembly) and installed OAuth2 Colab CLI. No Mac package installation is required. Unset PYTHONPATH. `--colab /ABS/installed/colab` selects the existing executable; no provider/auth substitution.

```text
python /ABS/SHARED/scripts/driver.py prepare --config /ABS/JOB/voice-config.json --work /ABS/JOB/voice-run-01
python /ABS/JOB/voice-run-01/driver.py run --work /ABS/JOB/voice-run-01 --colab /ABS/installed/colab
python /ABS/JOB/voice-run-01/driver.py status --work /ABS/JOB/voice-run-01 --colab /ABS/installed/colab
```

`prepare` is offline and refuses existing work directories. `run` checks usage/sessions, refuses foreign/ambiguous adoption, allocates only T4, records immutable ownership, checks dependencies and installs only if missing and authorized. It creates the remote directory before upload, verifies uploaded hashes, and runs one isolated inference process/model. Whole-run watchdog includes model load/download allowance plus chunk budget; it is not a phoneme/quality check. Two local locks serialize one work directory and this account's shared runtime operations across bots. Other tools must still respect session ownership.

Use a tracked detached local process for long runs; the bot reads durable `status.json`/`driver.log` rather than repeatedly polling with LLM turns. Driver errors are not speech completion. Model/download quota or compatibility errors remain concrete blockers, not reasons to switch route or reinstall the Mac.

## Recovery and teardown

A local CLI timeout may leave the remote running. The driver records `AWAITING_REMOTE_INSPECTION`; it never launches synthesis twice. Invoke:

```text
python /ABS/JOB/voice-run-01/driver.py recover --work /ABS/JOB/voice-run-01 --colab /ABS/installed/colab
```

`recover` downloads filesystem status first (no kernel execution). RUNNING/unknown/mismatched state blocks stop/retry. Terminal state permits retrieving the exact archive, checking safe member names, binding/ledger/WAV hashes and full decode, then stopping only the matching owned runtime. Failure archives/partial outputs remain available for a bounded explicit repair; automatic re-synthesis of missing chunks is not implemented. Do not delete evidence or claim that retrieval itself repairs a failed chunk.

If the archive is already downloaded, `finish` validates it, confirms teardown and assembles locally. Setup/upload errors before generation preserve the owned runtime for inspection; do not blindly stop an in-flight install or allocate another GPU. CLI syntax is `exec -s SESSION -f LOCAL.py --timeout N`, not `-c`.

## Sample review and full narration

Start with a representative sample on a new/unverified environment. Results remain `ASSEMBLED_PENDING_LISTENING_REVIEW`. Full mode requires `sample_review` pointing to a JSON receipt with:

- matching `job_id`, `reference_sha256`, `source_chunks_sha256`;
- actual `sample_path` and matching `sample_sha256`;
- `reviewed_by`, `coverage_accepted: true`, `likeness_accepted_by_owner: true`.

Only record these after actual review; technical measurements cannot grant them. Then prepare a fresh full-mode work directory and new session name using the approved whole chunk list. Do not replay the sample automatically or infer full approval from an unreviewed WAV. Speech review, exact real-audio visual proof, full video export approval and publishing are separate gates.

Assembly preserves raw audio, measures sample-based timing and envelope, uses the existing explicit pauses/fades, and never silently changes pitch/rate/EQ. Inspect actual speech coverage, pronunciation and joins; report listening limits.

## Verification limits

`python -m unittest discover -s /ABS/SHARED/scripts -p test_driver.py -v` runs isolated offline fixtures, including sample/full assembly, input/permission/review binding, foreign session refusal, timeout recovery and unsafe archive rejection. Fixture audio exists only in tests, never in the production driver. Passing fixtures does not prove a new live Colab run or voice likeness. Live verification on 2026-10-19: this reusable driver processed one approved Remotion chunk on a fresh free T4, checked upload hashes, generated/downloaded/decoded it, assembled a 5.20s master including its explicit pause, and stopped only its owned runtime; server readback showed no active sessions. Evidence is retained in the current job voice-v4/shared-driver-sample-01/verification.json. This proves a single-chunk pipeline, not full multi-chunk live reliability or speech/likeness acceptance. Full-mode multi-chunk assembly is tested offline; live full narration and subjective review remain pending.
