# Architecture

The Stage 2 dry-run prototype has four planes: a sanitized AI OS for goals and policy,
this public monorepo for reusable code and synthetic tests, a private local workspace for
candidate/application data, and a later isolated Hermes runtime. SQLite is operational
authority. Hermes memory, reports, and generated scores are not canonical facts.

The implemented flow is local fixtures → normalization → deduplication → deterministic
policy → explainable scoring → redacted report. Exact approvals bind any mock submission
to one job, recipient, payload, attachment set, and expiry.
