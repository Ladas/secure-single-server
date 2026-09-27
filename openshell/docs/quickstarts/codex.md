# Codex sandbox recipe (experimental)

Follow the [shared setup](common.md), selecting `harness=codex` and the dev profile.
The default sandbox name is `codex-dev`; `connect.sh` launches the Codex CLI.

Praxis integration is unsupported: `create.sh --config` fails before creating a
sandbox. Standalone experiments use an explicitly registered provider binding
with `--provider NAME`; SSH does not forward credentials. Real-provider tool tasks
and retained CLI sessions remain unqualified. See [AWS validation](../../../bootc/VALIDATION.md).
