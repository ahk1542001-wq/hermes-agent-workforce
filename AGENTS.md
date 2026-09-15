# Hermes Agent Workforce boundaries

This monorepo contains independent agent packages under `agents/`. Package
source and tests are authoritative for package behavior, with the approved
design specification defining intended interfaces.

Keep the repository public-ready: use synthetic examples only and never add
credentials, personal data, private documents, session artifacts, or
machine-specific paths. Tests are local and deterministic; they must not make
network, provider, model, or live-service calls.

Do not create a second root Python environment or shared library. Run the
package checks from the package directory, or run `./scripts/verify_all.sh`
from the monorepo root. Never publish, deploy, push, submit, or perform other
live external actions without explicit approval.
