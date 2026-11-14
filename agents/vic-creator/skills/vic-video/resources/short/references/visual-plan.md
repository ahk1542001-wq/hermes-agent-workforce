# Object/action execution contract

Read this plus the selected style; run helpers without reading their implementations unless a concrete error requires it. Use existing calibrated renderer and semantic operations. Author fresh data rather than rebuilding a film from `box()`/`label()` calls. This is a first-party implementation of object/action planning, not an installation or copy of an upstream engine.

## Inputs

`job.json` uses audio/envelope/chunks/duration_s/assets/rigs/palette as in production-mechanics. Add `visual_plan: "visual-plan.json"`. Timed `shots` must each have a unique `id`, start/end, background and calibrated presenter choice. No `scenes` file is needed on this route. Preparing an existing frozen legacy build is not required just to preserve/view it; use a fresh revision for production.

`visual-plan.json` has `style: "visual-story"` or `"ui-motion"`, and one ordered record per timed shot:

```json
{
  "style": "visual-story",
  "shots": [{
    "id": "scene_a",
    "primary": "person",
    "objects": [
      {"id":"person","kind":"sprite","asset":"actor","meaning":"story participant","x":60,"y":300,"w":520,"h":620},
      {"id":"note","kind":"sheet","meaning":"a specific input","x":590,"y":450,"w":150,"h":190,"ink":false},
      {"id":"receiver","kind":"folder","meaning":"the receiving place","x":620,"y":850,"w":300,"h":260}
    ],
    "actions": [
      {"op":"write","object":"note","at":0.5,"duration":1,"result":"input becomes visible on the note"},
      {"op":"transfer","object":"note","target":"receiver","at":1.8,"duration":1.4,"to":[680,890],"result":"the input arrives at its receiving place"}
    ],
    "labels":[{"text":"short topic-specific label","x":540,"y":230,"size":36}]
  }]
}
```

This example explains schema only; design fresh meaning, composition, timing and artwork for the actual topic. A reusable semantic renderer is not a requirement to reuse its sample character. Pick fresh story objects, actions and receiver relationships from the approved storyboard. Keep a coherent story/palette and choose shot length for actual speech. A supported operation failing to express a necessary action is a capability blocker, not permission to substitute paragraphs. Report the exact missing capability. An explicit owner-authorized extension must be isolated, validated and bound to a fresh build; do not claim unsupported actions exist or modify a running frozen build.

## Available operations

- Concrete objects: `sprite` (existing job-local illustration alias), `sheet`, `folder`, `device`, `notebook`, `token`. Object `{x,y,w,h}` uses top-left pixels; sprites preserve aspect and fit the box. Optional color/paper/ink chooses relevant look/state. No generated letters or compulsory topical icons are baked in.
- `move`: object travels to top-left `to:[x,y]` and retains opacity (apart from its intentional lifecycle fades). Use it for persistent slot assembly: delivered photo/name/date/result items must remain full-contrast at their real receiver destination.
- `transfer`: move toward a declared visible `target`, intentionally ending at45% opacity before lifecycle fades. Use only for a deliberately faded/consumed handoff, not a persistent final photo/name/date/result that needs full contrast. Destination must visibly meet the target; use `move` with the same receiver contact for persistent arrivals.
- `write` / `erase`: actual strokes grow/shrink within a sheet, notebook or device, with readable resulting hold.
- `open`: folder/notebook cover moves; use only when the mechanism needs opening.
- `pose`: sprite uses an existing calibrated rig and named `cue`. Action local `at` plus shot.start must match rig film-global time/duration. The retained rig library controls measured local deformation.

Every action has shot-local at/duration and a plain-language visible result. Every shot needs a concrete large primary, a meaningful operation and at most3short labels. Follow the selected display-text mode in SKILL.md; do not repeat the same point in both caption and object card. Label single phrases must fit actual loaded Myanmar glyph bounds; Unicode length limits are only a paragraph guard, not a translation of the Chinese8-character rule. Mechanism/evidence inserts can use ui-motion. Visual-story needs relevant narrative illustration(s); the VIC presenter does not count as the story character. This is not a fixed generation quota: generate relevant fresh artwork for a new topic using the available authorized image capability; reuse for same-film continuity or explicit owner-selected cross-topic reuse and disclose it. Regression stubs/learner assets are test fixtures, not production defaults.

## Preflight / export / review

Run prepare_job.py before rendering; it rejects missing illustration/asset, absent objects/operations, invalid receivers, no-op movement, small primary, overlong label/too many labels, out-of-range timing/geometry, and conflicting action intervals. Bind the plan into the same immutable build as audio, captions and images. check_job.py verifies renderer states against every plan shot/object and samples operations throughout the source timeline, plus rig/layout/encoded technical checks. These deterministic checks cannot prove artistic quality or factual meaning.

After exporting, check with `--movie` (source-only QA cannot close delivery). Main orchestrator performs a distinct post-render QA phase and must view encoded before/operation/result moments, each cut and relevant voice/motion, with candidate hash and explicit coverage limits. Its JSON uses:

- movie_sha256; role=`main-orchestrator-reviewer`, review_phase=`post_render` (legacy `independent-reviewer` remains supported); reviewer_session (real attested identity/session); verdict=`PASS` or `FAIL`.
- shots: one per plan ID, verdict, observed_objects (ordered IDs), observed_actions (ordered operation names), observation, at least2times_s inside that shot, and job-local extracted frame paths in frames.
- defects list; nonempty limits list describing actual unavailable/limited coverage. Frame samples do not certify continuous listening or natural acting. Do not invent a reviewer/session or owner acceptance.

Run `scripts/deliver_job.py --job JOB --movie final.mp4 --qa encoded-qa.json --review creative-review.json`. It refuses source-only/stale/incomplete evidence and main reviews without the explicit post_render phase. Main review is not independent review and must not be labelled as such. A successful receipt says REVIEWED_CANDIDATE_PENDING_OWNER_ACCEPTANCE, never automatic owner approval. The report binding verifies attribution/evidence consistency, not the truth of a review. Owner acceptance and publishing stay separate.
