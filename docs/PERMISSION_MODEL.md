# Video production permission model

1. Main prepares a brief and source-backed narration/storyboard for owner review.
2. Actual scoped permission is required before sending script/reference audio to an external runtime, allocating compute, or installing runtime dependencies/model weights.
3. A representative speech sample needs actual listening and owner likeness acceptance before full narration.
4. A real-audio visual proof needs exact owner acceptance before full video export.
5. Main performs factual, creative and encoded technical review; the owner accepts the final candidate.
6. Publication is a separate external action and requires actual authorization.

Authorization JSON is an attestation, not permission by itself. Worker reports, hashes, frame counts, silence statistics and export success cannot accept voice identity or creative quality. Interrupted jobs resume verified checkpoints rather than silently rerunning inference. Stop only a runtime owned by the current job.
