# Export verification

Locally verified for this public export:

- 16 shared Voice offline integration tests: PASS.
- 5 sample-based paper-timing tests: PASS.
- 8 synthetic presenter geometry tests: PASS.
- Fresh profile dry-run, two-profile copy, shared Voice-path resolution, refusal to overwrite and no-auth-copy checks: PASS.
- Python source compilation and exact allowlisted release/public-boundary scan: PASS.

Run `python3 -B scripts/verify_video.py` to repeat. CI runs the video suite separately from the existing Job Scout suite. Local results above are not an assertion that a pending CI run passed.

Original live profiles, keys, recordings, media jobs and the existing Job Scout implementation were not modified. No fresh model/image/voice inference, Colab allocation, paid compute or full five-style render was performed. The published gallery shows historical individual films; this source export requires documented runtimes and your own authorized assets.
