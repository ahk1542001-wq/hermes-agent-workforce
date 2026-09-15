# Hermes Agent Workforce

Hermes Agent Workforce is a local-first monorepo for independent, privacy-
preserving agent packages.

The current package is `agents/job-scout`. Each package owns its runtime and
tests; the root verification entry point delegates to that package.
