# Upstream Decisions

- `MadsLorentzen/ai-job-search` v1.7.1, MIT: reference-only; no code copied.
- Agent-Reach: deferred and not installed; web/RSS reconsideration needs a separate review.
- LinkedIn-AI-Job-Applier-Ultimate: rejected as a runtime/dependency because stealth,
  bypass, auto-submit, session, privacy, and exact-approval behavior conflict here.
- Scrapling: deferred and not installed; only a separately pinned parser review is possible;
  stealth, proxy, browser fingerprinting, MCP, and anti-bot paths remain excluded.
- Career-Agent 0.2.0 at `dd7f0a8c7dd5f893ad729231aa1afb5cee58033e`, MIT:
  reference-only. Private-root, symlink, lock/revision, atomic-write, source-health,
  provisional scoring, pursuit/interview/debrief, tracker recovery, loopback security,
  release allowlist, and privacy-scan concepts informed the design. No source,
  instructions, JSON state model, or Node runtime was copied.
- Hermes later consumes stable `web_search`/`web_extract` envelopes. The current Stage 3
  pilot imports local feed snapshots and adds no Tavily/Firecrawl SDK or key; any live
  search and bounded extraction test remains a separate approval gate.
- Vertex AI is a later optional model provider, not search, and is unused in Stage 3.
- Hermes baseline observed was 0.21.0; latest observed was 0.21.3. Updating is excluded
  and needs a separate Stage 4 security/backup/rollback review.
- Current Hermes search and extract selection was unavailable Exa. Stage 3 must explicitly
  verify a provider pair; this stage changes no credential or Hermes configuration.
