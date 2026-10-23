# OpenShell 0.1.3 and OpenClaw 2026.9.9 upgrade

This upgrade replaces the coordinated OpenShell runtime with the public upstream
v0.1.3 gateway, supervisor, and isolation images. OpenClaw uses the public upstream
v2026.9.9 image. All image digests and architecture-specific CLI checksums are
committed in [images.env](https://github.com/redhat-et/secure-single-server/blob/main/openshell/configs/images.env).
The previously used downstream repositories had not published these versions at
the time of qualification. The new workload containers use upstream Debian-based
runtimes; the deployment host and bootc OS remain RHEL 9.

The OpenShell CLI is fetched from the versioned GitHub release, checked against
the committed SHA-256, and then installed. Bootc copies that same verified binary
from its isolated build context. Schema tests mount the verified CLI into a
network-disabled container. Downloads fail closed on checksum mismatch.

The subsequent [real-model deployment tests](upgrade-0.1.3-e2e.md) qualify
manual installation and actual bootc OS boot/switch with both harnesses.

## Required migration

Use the [upgrade runbook](../../openshell/docs/upgrade.md): export required work,
delete every old sandbox, back up gateway state, upgrade all components together,
and recreate sandboxes. The tests below use a fresh gateway and do not qualify an
in-place database migration or a booted bootc OS rollout.

- Removed the v0.1.2 `guest_tls_cert` and `guest_tls_key` configuration fields,
  which v0.1.3 rejects. Gateway TLS verification, administrator mTLS and sandbox
  JWT authentication remain enabled.
- Wait for the supervisor's initial policy-revision acknowledgement before the
  first OpenClaw model turn. The old provider-environment log marker is obsolete.
- OpenClaw runs as upstream UID 1000. Its application is in `/app`; the policy
  disables automatic working-directory write grants and keeps `/app` read-only.
  Model files live in `/home/node/.openclaw/workspace`; the bounded runner sets
  `HOME=/home/node` explicitly rather than trusting the SSH session home.
- `exec` remains excluded from model tools. A process-group signal probe must
  still return `EPERM`, while a direct child-PID probe and cleanup must work.

## AWS qualification

Disposable RHEL 9 x86_64 `m7i.2xlarge` in `us-east-1`, enforcing SELinux,
rootless OpenShell owned by `openshell-svc`, Podman 5.8.2. Tests use synthetic
credentials and a controlled streamed-model fixture; they need no paid account
or GPU. Saved logs remain outside the committed tree.

| Check | Result |
| --- | --- |
| Verified release CLI | OpenShell 0.1.3 |
| Fresh gateway registration and sandbox creation | Passed |
| RHEL bootc base, OpenClaw and OpenCode container builds and image contracts | Passed |
| Pinned CLI schema and policy-boundary checks | Passed for all 19 policies |
| OpenClaw in actual OpenShell | Passed: streamed write, continuation, exact file readback, Praxis positive control, direct-route EACCES, no provider-key environment |
| Native OpenClaw/Praxis authentication contracts | Passed: bearer, custom route prefix, invalid-key rejection, and credentialless |
| Native OpenCode/Praxis model and tool contracts | Passed: bearer-authenticated and credentialless routes, real streamed write and bash, exact command-produced file, final response |
| OpenCode in actual OpenShell | Passed: streamed write and bash tools, independent command-produced file readback, final model response, Praxis positive control, direct-route EACCES, no provider-key environment |
| OpenCode provider attachment and controlled HTTP policies | Passed: attached/unbound credential canaries, reachable allow control, explicit EACCES deny with no request |
| Application write and process-group negative controls | Passed: `/app` write EACCES, group signal EPERM, direct child signal/cleanup succeeds |

The hosted Docker OpenClaw fixture runs as root, matching AWS qualification:
upstream UID 1000 creates private files that a different host UID cannot read or
clean up. This only affects the disposable test process; the deployed OpenShell
gateway remains rootless. For Docker, use
`sudo env CONTAINER_ENGINE=docker python3 tests/openshell-praxis/openclaw-native.py`.

Both harnesses are tested against the same upgraded gateway. The OpenCode workload
image remains unchanged; its integration must still pass when OpenShell changes.

Repeat native client/gateway checks with
`python3 tests/openshell-praxis/openclaw-native.py` and
`python3 tests/openshell-praxis/opencode-native.py` (run serially). On a prepared disposable RHEL
host, run `sudo bash tests/openshell-praxis/openclaw-runtime.sh`, then
`sudo bash tests/openshell-praxis/opencode-runtime.sh`. Wait for each command to
finish cleanup before starting the next: they share loopback fixture ports. The hosted
[OpenShell workflow](https://github.com/redhat-et/secure-single-server/blob/main/.github/workflows/openshell-validate.yml) uses the new
prover, verified CLI, offline download controls, and native OpenClaw and OpenCode contracts.
The privileged OpenShell runtime job runs both harnesses and remains opt-in on
`main` only. The offline fixture test covers OpenCode's streamed write → bash →
final-response sequence.

The [earlier qualification](openclaw-praxis.md) describes the previous versions
and real Qwen GPU results. It is historical evidence, not a real-model result for
this upgrade. Paid OpenAI, real GPU inference, browser/gateway authentication,
retained sessions, OpenClaw automatic command execution, and booted OS rollout are not
qualified by the synthetic upgrade tests.
