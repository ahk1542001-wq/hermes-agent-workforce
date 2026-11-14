# Upstream runtime boundaries

This source release includes VIC-authored workflow instructions, rendering/adaptation helpers and the shared Voice driver. It does not install or execute external repositories.

- Hermes: separately installed agent host, tools and native worker configuration.
- VoxCPM2: external reference-conditioned speech model; model weights not redistributed.
- AniDoodle: external cartoon runtime, Apache-2.0; upstream license retained with exported extensions.
- Huashu Art Motion: external paper/Canvas engine, with separate artwork/font restrictions.
- KAPE design/helpers, HyperFrames and GSAP: spatial-style prerequisites; no third-party mascot is bundled as VIC identity.

Review exact upstream revisions, dependencies, licenses, network behavior and asset rights before installation. Do not assume latest upstream HEAD matches historical owner films. See [runtime map](../agents/vic-creator/skills/vic-video/references/runtime-map.md) and [attribution](VIDEO_ATTRIBUTION.md).
