# Bootc validation — 2026-09-25

This is the historical cloud-profile report. For the updated OpenShell pins and
local CPU/GPU Qwen route, see [2026-09-28 vLLM validation](VLLM-VALIDATION.md).

## Published quickstart verification (October 2)

The OpenCode and OpenClaw `v0.1` bootc quickstarts were qualified in AWS
`us-east-1` from their exact published Quay digests, not from locally rebuilt
images:

| Variant | Published `v0.1` digest | Test AMI | Test instance |
| --- | --- | --- | --- |
| OpenCode | `sha256:4effd535f8c7111f540ecc4f015a2a17b2b1c6d5c8fdd582e9d162a6778cb734` | `ami-0d9e2d1a1160563af` | `i-006c2e1397993b555` |
| OpenClaw | `sha256:f2dbdfcc449a2753202b0438c2dd29e68641a07aea0647bc7184920c500580e6` | `ami-0c3d00a28112c3f43` | `i-08578a1f22257f2b6` |

Each VMDK was built on a disposable RHEL 9.8 x86_64 EC2 builder with
`quay.io/centos-bootc/bootc-image-builder@sha256:afeffdb5a7ab6bb9d0593b5765412c4d821a9492dbaf26bb5a494e27181d2019`,
imported through the test S3 bucket, and registered as a separate AMI. The
builder instance was `i-045d9a5c2b74a5369`. Registry tags are mutable; the
digests above, not the `v0.1` tags, are the reproducibility record.

Both booted hosts reported the exact source digest through `bootc status`,
activated `secure-single-server.service`, rendered the digest-pinned
`sandbox_runtime_image`, kept SELinux Enforcing, enabled lingering for
`openshell-svc`, and bound ports 8090/8091 only to `127.0.0.1`. OpenShell
reported `0.1.2-rhaiv.0`.

The selected dev sandbox reached Ready on both hosts. OpenCode reported
`1.18.31`; OpenClaw reported `2026.9.5 (ec9c1a1)`. File creation and readback
inside `/sandbox` passed. The controlled policy qualification passed on both
hosts: the allowed request reached the local fixture and returned HTTP 401,
while the denied request returned `EACCES` without a server-side hit. Podman
inspection reported two CPUs, 4 GiB, and 2048 PIDs for each sandbox.

Model routing and real inference were not active. OpenClaw's browser/service
command remains separately unqualified; this run verified its sandbox, CLI
version, shell access, policy, and runtime limits.

Built with rootful Podman 5.8.2 on an AWS RHEL 9.8 x86_64 PAYG builder.
Application services run rootless on the booted host. No real provider keys
or paid model requests were used.

RHEL base input:

```text
registry.redhat.io/rhel9/rhel-bootc@sha256:cfe6b13fa436d39088cc525254f5de9f4e0c7da8b8f0b44b926acd11cdeb42d7
```

Praxis, OpenShell and harness inputs use the existing repository pins in
`scripts/common/lib.sh` and `openshell/configs/images.env`. The native OpenShell
CLI reports `0.0.116-rhaiv.14`; the sandboxed OpenCode CLI reports `1.18.31`.

## Built artifacts

All are in the builder's **rootful** Podman store under
`localhost/secure-single-server`. They have not been published to a registry.
Image IDs identify the configuration independently of archive/manifest format
conversion during transfer.

| Tag | Image ID prefix | Uncompressed size |
| --- | --- | --- |
| `base` | `41e36b93563b` | 2,073,762,211 bytes |
| `opencode` | `a45b748f5afd` | 2,073,803,386 bytes |
| `openclaw` | `94c2ae833351` | 2,073,803,899 bytes |

The base layers are shared. Each harness adds about 40 KiB, excluding OCI
metadata. Workload containers are fetched separately after boot.

## Checks

- All tested builds completed and passed `bootc container lint`: 12 checks passed,
  one skipped, one `/var` layout warning. The warning concerns cloud-init and
  dhclient directories, ldconfig cache and inherited build information; no
  application state or credentials are embedded.
- All tested images passed `bootc/test-images`, including native CLI execution, enabled
  startup service, absence of RHUI keys and machine secrets, and harness
  argument-validation regression checks.
- Five local build/harness regression tests passed, along with ShellCheck,
  existing gateway static checks and OpenShell policy static checks.
- A disposable RHEL EC2 instance was converted with `bootc install
  to-existing-root`. Bootc reported the selected image; the OS filesystem was
  read-only and SELinux remained enforcing.
- Switching to the final OpenCode image required two new layers (38.4 kB).
  After reboot, `bootc/test-host opencode` passed, the packaged creation script
  created a `Ready` dev sandbox, and `opencode --version` succeeded over its
  SSH proxy. OpenCode's review sandbox reached `Ready`, but CLI startup was
  denied when it tried to create `/sandbox/.local/share`; the read-only policy
  was retained and this profile is not qualified.
The install/update tests use locally transferred images and the
`containers-storage` transport, not a published registry or AMI. Initial
installation used a test-specific SSH key and retained the disposable machine's
SSH host identity; neither is in the built OS images.

## Remaining qualification

Registry-based OS rollout/authentication, AMI disk-image export, forced registry
outage/recovery, full network-policy denial tests, and real-provider inference
remain unqualified. The existing per-harness Praxis provider configuration also
needs its separate integration acceptance. The bootc profile currently uses
in-memory quotas; it does not qualify Valkey persistence.
The base-only and OpenClaw images passed build/container checks but have not
been separately booted or qualified for sandbox CLI execution.

## PR #3 review regression run (September 25)

The shared gateway template now owns the UID mapping and explicit loopback bind
previously applied only by bootc. All tested images were rebuilt on the same
native AWS RHEL 9 builder and passed `bootc/test-images`.

Additional review checks:

- All 16 standalone/rendered integrated policy files passed the exact pinned CLI
  parser in a network-disabled container. Numeric ports now survive rendering.
- Five build tests, three harness behavioral tests, 33 existing remote/AWS tests,
  shared-gateway static checks and ShellCheck passed. The workflows were also
  reviewed with a locally installed `actionlint`; that review is manual today
  because no CI job runs it yet.
- HTTP 200, 401, 403 and 500 all passed the probe's reachability regression, with
  four requests recorded by the local test server. HTTP errors are not denials.
- Native mutable-RHEL lifecycle: install Praxis with dummy secrets, install the
  OpenShell add-on, status, rerun add-on, remove add-on, status, reinstall, remove,
  and uninstall Praxis. The Praxis scenario/manifest hashes remained unchanged
  through add-on operations; final uninstall preserved secrets and Valkey data.
- Fresh gateways require explicit provider-profile import. The synthetic provider
  fixture imported its own profile, created bound and unbound sandboxes, and
  confirmed raw canaries were absent in both. No real provider credentials were used.

The strict runtime network test did **not** pass: the proposed Praxis alias
`host.openshell.internal` did not resolve in the sandbox. A controlled destination
using `host.containers.internal` also failed its positive control with EACCES;
forcing a guessed loopback proxy was not a working route either. None of those
failures is counted as a policy denial. Integrated inference, direct-provider
network enforcement and real tool tasks remain unqualified. OpenClaw now
reject integrated `--config`; OpenCode's config path is explicitly experimental.
The runtime workflow is an opt-in qualification gate and will fail while those
network prerequisites are unmet. Existing sandbox deletion/recreation also proved
unreliable during canary testing; retained harness/session claims were removed.

[Review resolution matrix](../openshell/REVIEW-FOLLOWUP.md) maps F01–F10 to changes
and the remaining qualification boundaries.

## Shared gateway cleanup regression (September 25)

After extracting the shared certificate/configuration/startup helpers, all four
images rebuilt and passed image checks on native AWS RHEL 9 x86_64. Mutable
OpenShell install, reinstall and uninstall passed. Three focused regressions cover
the two startup modes, preserved CLI registration and failed health checks;
build, harness, probe, static, ShellCheck and workflow checks also passed.

The provider/network qualification gaps above remain unchanged.
