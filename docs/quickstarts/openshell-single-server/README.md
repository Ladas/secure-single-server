# OpenShell single-server harness deployment

This guide deploys **OpenCode or OpenClaw** on one trusted RHEL 9 x86_64 server
or bare-metal host with OpenShell as the agent security boundary. It is written
for an administrator who wants the harness available remotely, while keeping its
tools, filesystem access, and network access under an explicit policy.

Use the manual path to understand each step. Use the bootc path when you want
the project's already-built OpenShell/harness image applied to a server quickly.
Model routing is intentionally out of scope here; the existing
[OpenShell + Praxis workflow](../openshell-praxis/README.md) remains available
for administrators who select that integration.

## Current qualification status

| Harness | Qualified in the single-server OpenShell path | Explicitly not qualified |
| --- | --- | --- |
| OpenCode | Sandbox creation, CLI version, shell/file operations, policy allow/deny, runtime limits | Optional Praxis model routing and real inference; the narrower `review` profile |
| OpenClaw | Sandbox creation, CLI version, shell access, policy allow/deny, runtime limits | Browser/service command, authentication, retained sessions, `--backend`, and Praxis integration |

## AWS verification

On 2026-10-02, the manual path was exercised on a disposable RHEL 9 x86_64 EC2
host in `us-east-1`. It created Ready OpenCode and OpenClaw sandboxes, passed
the controlled allow/deny policy test, verified two-CPU, 4 GiB, 2048-PID
limits, confirmed SELinux Enforcing and lingering, and showed ports 8090/8091
bound only to loopback.

The bootc path was then qualified in the same region from the exact published
Quay digests, not from a locally rebuilt image:

| Variant | `v0.1` digest at validation |
| --- | --- |
| OpenCode | `sha256:4effd535f8c7111f540ecc4f015a2a17b2b1c6d5c8fdd582e9d162a6778cb734` |
| OpenClaw | `sha256:f2dbdfcc449a2753202b0438c2dd29e68641a07aea0647bc7184920c500580e6` |

Both published variants booted the recorded digest, started the reconciliation
service, rendered the pinned `sandbox_runtime_image`, created Ready sandboxes,
passed file-write and controlled allow/deny tests, and reported the same
runtime, SELinux, lingering, and loopback-only results as the manual path.
Model routing was not active during this OpenShell qualification; follow the
Praxis guide for that separate model-path test. See the
[bootc validation record](../../../bootc/VALIDATION.md) for the full AWS
evidence.

## Why OpenShell

OpenCode and OpenClaw provide the agent experience: prompts, model calls, and
tools. OpenShell supplies the operational boundary around that experience:

- Tools run in a sandbox under a locked service account and rootless Podman,
  not with an unrestricted interactive host login.
- Filesystem rules distinguish read-only host paths from writable workspace
  paths, reducing accidental or prompt-driven changes outside the sandbox.
- Network rules are per-binary allowlists rather than broad host egress.
- Each sandbox has default Podman runtime ceilings of two CPUs, 4 GiB of RAM,
  and 2048 PIDs.
- Policy decisions are visible in OpenShell logs and acceptance tests, so a
  denial can be distinguished from an unrelated connection failure.
- The bootc image packages the pinned OpenShell control-plane and selected
  harness image references, plus policy files, as one reviewed, rollback-capable
  host deployment.

This is an important improvement over running a harness directly on a server:
the agent can remain useful without simultaneously receiving unrestricted
access to the host account, host filesystem, and arbitrary network destinations.

The current deployment is for a **trusted single operator**. It is not
multi-tenant authorization, and it does not inspect prompts or guarantee that
code produced by a model is trustworthy. Read the
[threat model](../../../openshell/docs/threat-model.md) before exposure to
valuable data or shared use.

## What the policy protects

OpenShell profiles are applied when a sandbox is created. You do not install a
policy afterward and hope the harness uses it.

| Control | What the profile declares | Default `dev` behavior |
| --- | --- | --- |
| Filesystem | Read-only and read-write path sets, plus optional workspace inclusion. | Inside the sandbox, `/usr`, `/lib`, `/lib64`, `/etc`, `/proc`, `/dev/urandom`, and `/opt` are read-only. `/sandbox`, `/home`, `/tmp`, and `/dev/null` are writable. |
| Network | Named endpoint allowlists scoped to exact harness/tool binary paths. | OpenCode permits selected model, OpenCode registry, GitHub, and npm endpoints. OpenClaw permits selected model, GitHub, and npm endpoints. Other destinations are denied. |
| Runtime | Rootless Podman execution with per-sandbox CPU, memory, and PID limits. | Two CPUs, 4 GiB of memory, and 2048 PIDs by default; these are per-sandbox limits, not a host-wide budget. |
| Credentials | No provider key is forwarded by the SSH helper. | Standalone credentials must be explicitly registered and attached. Integrated model-routing mode rejects direct provider attachment. |

The default development endpoints are:

| Harness | Permitted on TCP 443 |
| --- | --- |
| OpenCode | `api.anthropic.com`, `api.openai.com`, `opencode.ai`, read-only `api.github.com`, `github.com`, and `registry.npmjs.org`. |
| OpenClaw | `api.anthropic.com`, `api.openai.com`, read-only `api.github.com`, `github.com`, and `registry.npmjs.org`. |

The exact endpoint and filesystem rules differ by profile. Review the policy
before deployment rather than inferring it from the profile name:

- [OpenCode policies](../../../openshell/harnesses/opencode/profiles/dev/policy.yaml)
- [OpenClaw policies](../../../openshell/harnesses/openclaw/profiles/dev/policy.yaml)
- [Full policy qualification contract](../../../openshell/docs/policy-walkthrough.md)

Start with the `dev` profile for the first smoke test. It is intentionally wide
enough for the CLI to operate; the manual section records current harness
limitations. Treat a move to `automation`, `interactive`, or a custom profile as
a reviewed policy change with fresh positive and negative network tests.

Important limits:

- `landlock.compatibility` is `best_effort`; filesystem protection can degrade
  on an unqualified kernel. Record actual runtime enforcement.
- GitHub API access is method-restricted, but Git-over-HTTPS to `github.com` is
  not read-only. An allowed endpoint can still receive data from a malicious
  harness or tool.
- A policy parsing or sandbox Ready result does not prove enforcement. Use a
  successful positive control plus an explicit denial when qualifying a host.
- Deleting a sandbox can destroy work. Export anything you need first.

## Manual RHEL deployment

Use a dedicated RHEL 9 x86_64 host. For first qualification, use a disposable
instance before changing a long-lived server. On the host, install Podman,
Python 3, OpenSSH clients, curl, and the SELinux management tools, then
transfer or check out the reviewed repository revision. Run from the repository
root:

```bash
sudo dnf install -y podman python3 policycoreutils openssh-clients curl
```

```bash
sudo openshell/scripts/install.sh --owner openshell-svc
```

The installer creates the locked `openshell-svc` account, enables lingering so
the gateway remains available after logout, and starts the loopback-only
OpenShell gateway with TLS/mTLS for the service operator.
It pre-pulls every pinned supported harness image; the selected harness is
chosen when its sandbox is created. If it reports that cgroup delegation needs
a host reboot, reboot and rerun the same installer.

Create the selected harness with its `dev` policy. The profile is part of the
create operation:

```bash
harness=opencode  # opencode or openclaw
uid="$(id -u openshell-svc)"
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  "$PWD/openshell/harnesses/$harness/create.sh" \
  --profile dev --name "$harness"-dev
```

Connect from the same owner environment:

```bash
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  "$PWD/openshell/harnesses/$harness/connect.sh" --name "$harness"-dev
```

OpenCode launches its CLI. OpenClaw opens a shell in the sandbox because its
service command and authentication are not yet qualified. Keep the checkout and
its parent directories readable by `openshell-svc`.

Use the `dev` profile for OpenCode. Its `review` profile currently denies the
CLI runtime-state directory, so sandbox creation can succeed while the CLI
fails. OpenClaw's `--backend` option is unsupported; it previously printed a
value without configuring anything. No OpenClaw browser workflow or retained
service session is qualified, and no management or browser port should be
published to make remote access work.

Each sandbox has a per-sandbox runtime ceiling of two CPUs, 4 GiB, and 2048
PIDs by default. To change a deployment under review, set
`OPENSHELL_SANDBOX_CPU` and `OPENSHELL_SANDBOX_MEMORY` in the same
service-owner environment used for `create.sh`; for example, `1` and `512Mi`.
These are not aggregate host reservations.

Standalone model credentials are never forwarded through the SSH helper. If a
reviewed deployment needs one, import an administrator-reviewed provider
profile, register the credential from a hidden prompt in the service-owner
environment, and attach it explicitly with `create.sh --provider NAME`:

```bash
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  bash -c '
openshell profile lint -f /path/to/reviewed-provider-profile.yaml
openshell profile import -f /path/to/reviewed-provider-profile.yaml
read -r -s -p "Synthetic provider key: " PROVIDER_KEY; printf "\n"
export PROVIDER_KEY
openshell provider create --name test-provider --type openai \
  --credential PROVIDER_KEY
unset PROVIDER_KEY
'
```

Use synthetic credentials first. If you select the optional OpenCode Praxis
integration, do not attach a direct provider: integrated mode rejects the
binding and the separate [Praxis workflow](../openshell-praxis/README.md)
documents its own qualification limits.

When creating a standalone sandbox that uses the registered provider, append
`--provider test-provider` to the selected `create.sh` command:

```bash
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  "$PWD/openshell/harnesses/$harness/create.sh" \
  --profile dev --name "$harness"-dev --provider test-provider
```

For a one-off network requirement, add `--policy-advisor` when creating the
sandbox. After the harness reports a denial and proposal, review and approve it
as the same service owner:

```bash
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  openshell/scripts/policy-approve.sh list HARNESS-dev
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  openshell/scripts/policy-approve.sh approve HARNESS-dev --chunk-id PROPOSAL-ID
```

The grant applies only to that sandbox instance and disappears when the sandbox
is recreated. Successful approvals are recorded in a local JSONL audit file.

Inspect the sandbox and remove it only after exporting needed work:

```bash
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  openshell sandbox list
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  openshell sandbox delete HARNESS-dev
```

Verify the runtime ceilings from the host rather than trusting the sandbox name:

```bash
repo="$PWD"
cd /
container_id="$(
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  podman ps --filter name=openshell-default--"$harness"-dev -q)"
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  podman inspect "$container_id" \
  --format 'cpus={{.HostConfig.NanoCpus}} memory={{.HostConfig.Memory}} pids={{.HostConfig.PidsLimit}}'
```

The expected default is `cpus=2000000000` (two CPUs), `memory=4294967296`
(4 GiB), and `pids=2048`.

Run the controlled policy qualification as the service owner from the reviewed
repository checkout:

```bash
cd /
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  bash "$repo/openshell/tests/openshell-policy.sh"
```

The test starts a local HTTP fixture, creates temporary allow and deny
sandboxes, proves the allowed request reaches the fixture, and proves the denied
request returns `EACCES` without reaching the server. A `401` from the fixture
is a successful positive control; an external website error is not.

## Bootc quickstart

The quick path uses the project's published RHEL bootc image. Select exactly one
harness variant:

```text
quay.io/redhat-et/secure-single-server-opencode:v0.1
quay.io/redhat-et/secure-single-server-openclaw:v0.1
```

At validation time, those tags resolved to the digests recorded in
[AWS verification](#aws-verification). Resolve them again before an auditable
deployment because registry tags are mutable.
The image contains the optional Praxis service, but it does not become a model
route until its separate secrets and activation workflow are configured; the
OpenShell sandbox checks do not depend on that service.

For an auditable deployment, resolve the mutable `v0.1` tag to its digest and
boot that digest. Run `skopeo inspect` on the host or another trusted system
with `skopeo` installed, record the digest separately from the tag, and run
`bootc switch` on the target host:

```bash
digest="$(skopeo inspect --format '{{.Digest}}' \
  docker://quay.io/redhat-et/secure-single-server-opencode:v0.1)"
printf 'Deploying digest: %s\n' "$digest"
sudo bootc switch "quay.io/redhat-et/secure-single-server-opencode@$digest"
```

Use an image that includes the `sandbox_runtime_image` fix. Before trusting an
older `v0.1` artifact, verify that its rendered gateway configuration contains
the digest-pinned `sandbox_runtime_image` setting; images built before that fix
may pull the wrong sandbox layer and fail during sandbox creation.

```bash
sudo grep '^sandbox_runtime_image' \
  /var/lib/openshell-svc/.config/openshell/gateway.toml
```

### Apply the image to an existing bootc host

On a booted RHEL image-mode host, stage the selected image and reboot:

```console
sudo bootc switch quay.io/redhat-et/secure-single-server-opencode@RESOLVED_DIGEST
sudo bootc status
sudo systemctl reboot
```

Use the OpenClaw image reference instead when that is the selected harness.
Switching variants replaces the selected harness configuration; it does not
migrate existing sandboxes. Export and recreate them as needed.

### Apply the image to a fresh single server or bare-metal host

For a fresh host, use the existing image as the input to Red Hat's
[bootc image builder instructions](../../../bootc/README.md#install-and-boot).
The resulting disk or bare-metal image contains the selected OpenShell and
harness deployment; no application container is embedded in the OS image. First
boot pulls the digest-pinned control-plane and selected harness images.

### Verify and create the sandbox

After boot, SSH to the administrator account and verify the deployment:

```console
sudo journalctl -u secure-single-server.service -b
sudo systemctl status secure-single-server.service --no-pager
sudo sss-bootc openshell --version
sudo sss-bootc openshell sandbox list
```

The default bootc service can leave its optional model-routing service waiting
for separately provisioned secrets while OpenShell is already ready. Complete
standalone model access with the provider guidance in
[Manual RHEL deployment](#manual-rhel-deployment), or select the optional
[model-routing guide](../openshell-praxis/README.md), before running the model
prompt below. The OpenShell policy and sandbox commands do not require that
optional service to be active.

Create and connect the sandbox with the selected policy:

```console
sudo sss-bootc harness create --profile dev --name opencode-dev
sudo sss-bootc harness connect --name opencode-dev
```

For the OpenClaw image, use `openclaw-dev` as the name. OpenCode launches its
CLI; OpenClaw opens a shell because its browser service command is not yet
qualified.

The bootc service uses locked, separate rootless accounts and enables lingering.
OpenShell listens only on loopback ports 8090/8091. Keep SELinux Enforcing and
do not expose the management port beyond the host. If OpenShell changes in a
new image, export work, delete pre-upgrade sandboxes, and recreate them as
described in the [upgrade runbook](../../../openshell/docs/upgrade.md).
Reach the host remotely through your normal administrator SSH path, for example
`ssh -t ADMIN_USER@RHEL_HOST`, and then run `sudo sss-bootc harness connect`.
Do not publish OpenShell's management port to make remote access work.

Confirm the runtime ceilings from the administrator account:

```bash
cd /
uid="$(id -u openshell-svc)"
sandbox=opencode-dev
container_id="$(
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  podman ps --filter name=openshell-default--"$sandbox" -q)"
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  podman inspect "$container_id" \
  --format 'cpus={{.HostConfig.NanoCpus}} memory={{.HostConfig.Memory}} pids={{.HostConfig.PidsLimit}}'
```

Use the selected sandbox name and expect the same two-CPU, 4 GiB, 2048-PID
limits used by the manual deployment.

To run the controlled policy qualification on a quickstart host, copy the
reviewed repository to a temporary service-readable location:

```bash
uid="$(id -u openshell-svc)"
reviewed_checkout="$HOME/secure-single-server"
sudo rm -rf /var/tmp/secure-single-server-policy
sudo install -d -m 0755 /var/tmp/secure-single-server-policy
for directory in openshell scripts configs; do
  sudo cp -a "$reviewed_checkout/$directory" /var/tmp/secure-single-server-policy/
done
sudo chown -R root:"$(id -gn openshell-svc)" /var/tmp/secure-single-server-policy
sudo chmod -R u=rwX,g=rX,o= /var/tmp/secure-single-server-policy
cd /
repo=/var/tmp/secure-single-server-policy
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  OPENSHELL_BIN=/usr/bin/openshell \
  bash "$repo/openshell/tests/openshell-policy.sh"
sudo rm -rf /var/tmp/secure-single-server-policy
```

## Test the harness

Run these checks after the sandbox is Ready and before giving it valuable work.
They are intentionally small enough to repeat after every image or policy
change. The model prompt assumes that the selected harness already has working
model access; the filesystem and network controls do not.

### 1. Prove model interaction

For either harness, once its model access is configured, use this prompt:

```text
In one sentence, explain why a network allowlist improves AI-agent security.
```

A useful response confirms the model path, not the policy. OpenClaw's pinned
service command and authentication are not qualified; use the shell checks below
to verify its sandbox environment.

### 2. Prove tool execution and writable workspace

For either harness with model access configured, use this prompt:

```text
Create /sandbox/openshell-check.txt containing the text "policy applied". Read
the file back and show its exact contents.
```

For either harness, you can also run this directly after connecting:

```sh
printf '%s\n' 'policy applied' > /sandbox/openshell-check.txt
cat /sandbox/openshell-check.txt
```

The file must exist outside the model response. An agent can describe an action
without executing it.

### 3. Prove policy-controlled network behavior

Use the controlled policy test rather than an arbitrary public endpoint. On a
manual deployment, run the service-owner command shown in
[Manual RHEL deployment](#manual-rhel-deployment). On a quickstart image used
for qualification, copy the reviewed repository to the host, make it readable by
`openshell-svc`, set `OPENSHELL_BIN=/usr/bin/openshell`, and run the same test
as that service user.

The suite proves both directions with a local fixture: the allowed request must
reach the server and return its known `401`, while the denied request must
return `EACCES` without producing a server-side request. Do not use a failed
GitHub, OpenAI, or example.com request as positive evidence; DNS failures,
timeouts, and unrelated network errors can look identical to a policy denial.

### 4. Exercise a small coding task

For OpenCode, use this prompt:

```text
Create /sandbox/add.mjs that exports add(a, b), create test_add.mjs with
node:test cases for (2, 3), (-2, -3), and (0, 0), then run
node --test --test-reporter=tap test_add.mjs.
```

Require nonzero passing tests and independently rerun the command after the
harness exits. This checks tool execution, file creation, and command completion
inside the sandbox.

## Continue

- [OpenShell threat model](../../../openshell/docs/threat-model.md)
- [Policy qualification](../../../openshell/docs/policy-walkthrough.md)
- [Bootc deployment details](../../../bootc/README.md)
- [OpenShell + Praxis integration](../openshell-praxis/README.md)
