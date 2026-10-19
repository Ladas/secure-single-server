# OpenShell 0.1.4 pin and compatibility review

This change moves the coordinated deployment from OpenShell v0.1.3 to v0.1.4.
The gateway, supervisor, and sandbox images are pinned by manifest digest; the
Linux CLI and policy prover are pinned to the release archives and SHA-256
checksums in [images.env](../../openshell/configs/images.env) and the
[OpenShell workflow](../../.github/workflows/openshell-validate.yml).

## Release review

- The new snap user-gateway mode does not apply to this repository's RPM and
  rootless-Podman deployment. No snap commands or paths are used.
- Gateway TOML already begins with `[openshell]` and `version = 2`, which
  v0.1.4 requires.
- Sandbox upload backpressure requires a matching CLI and supervisor. Both are
  upgraded together by the coordinated pins.
- v0.1.4 adds mTLS operator access to `GetProviderCredentials`. The gateway
  template explicitly sets `operator_enabled = false`; this deployment does not
  export provider credentials through that RPC.
- Stable provider credential placeholders remain opt-in and are not enabled.
- The v0.1.4 prover's fail-closed sibling-endpoint and solver-error behavior is
  covered by the workflow's pinned prover.
- SSH-forwarding fixes do not change the local gateway and native SSH proxy
  workflow used here.

Follow the [upgrade runbook](../../openshell/docs/upgrade.md), export needed
work, delete every pre-upgrade sandbox, upgrade all components together, and
recreate sandboxes from the new pins.

## Validation and scope

The release asset checksums and GHCR manifest digests were checked against the
upstream v0.1.4 release. Repository static checks compare the gateway,
supervisor, sandbox, CLI, and prover pins with the reviewed
[v0.1.4 release manifest](../../openshell/configs/releases/v0.1.4.json), while the workflow
keeps an independent prover trust anchor. The final local validation passed the
focused PR-queue suite (63 tests), bootc inference
routing suite (17 tests), OpenShell regression
suite (14 tests), bootc build suite (12 tests), ShellCheck, Bash syntax checks,
and `git diff --check`. A read-only GitHub dry-run selected
[issue 57](https://github.com/redhat-et/secure-single-server/issues/57), which
carries the `bot` label. The full local static suite reaches the expected
workstation limitation because `openshell-prover` is not installed; CI supplies
the pinned v0.1.4 prover.

A disposable AWS RHEL 9 instance was used to validate the watcher's core issue-57
path before the final host-side hardening. It selected issue 57, completed a real
OpenCode turn, and produced a reviewable patch bundle; the patch was not applied
or published, and the instance was terminated afterward. The final hardening was
then validated with the offline suites and live read-only dry-run above. The
earlier [0.1.3 real-model and bootc qualification](upgrade-0.1.3-e2e.md) remains
historical evidence; it is not repeated merely by changing the pins. Run the
opt-in runtime workflow and a real-model task before promoting a deployment that
requires fresh v0.1.4 runtime evidence.
