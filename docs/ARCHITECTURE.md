# Architecture

The Stage 3 local pilot has four planes: a sanitized AI OS for goals and policy,
this public monorepo for reusable code and synthetic tests, a private local workspace for
candidate/application data, and a later isolated Hermes runtime. SQLite is operational
authority. Hermes memory, reports, and generated scores are not canonical facts.

The implemented flow is synthetic fixtures or local feed snapshots → source parsing →
normalization → cross-source deduplication → authority-aware verification → deterministic
fail-closed policy → explainable scoring → revision-checked SQLite state → redacted report.
Exact approvals bind any mock submission to one job, recipient, payload, attachment set,
and expiry.
