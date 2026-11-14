# Video attribution and source boundaries

The new Creator/Voice packages contain public-adapted VIC instructions, current shared Voice scripts/tests and retained VIC rendering/adaptation code. Machine paths were generalized and local executable locations made configurable for the exported short renderer. The operational profiles were not changed.

- Hermes is the host agent platform. This repository does not claim to implement Hermes itself.
- VoxCPM/VoxCPM2 (`openbmb/VoxCPM2`) is the upstream speech model; model weights and their license are not redistributed. Review its model terms before use.
- AniDoodle by Alex Greenshpun is the Apache-2.0 cartoon runtime dependency; the full upstream engine is not redistributed here. Original license retained alongside exported cartoon extensions.
- Huashu Art Motion is the upstream paper engine dependency, MIT code with separate artwork/font exceptions. Restricted demo artwork, mascots and films are excluded.
- KAPE by Kenneth Villar/BrewedOps is a spatial-design/runtime reference; its MIT license is retained for adaptation provenance. User-facing style name is VIC Spatial Motion.
- HyperFrames, GSAP, Playwright, FFmpeg and NumPy remain separately installed dependencies under their own terms.

No upstream engine, fonts, music pack, third-party mascots, private reference audio, original conversations or accounts are bundled. Supply your own authorized assets. The root license does not override upstream licenses or grant rights to example video/audio media. Public source adaptation is tracked in `agents/vic-creator/export-provenance.json`; final release checks verify exported files. Keep original notices if adding upstream source later.
