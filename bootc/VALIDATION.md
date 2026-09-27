# Bootc validation — 2026-09-25

Built with rootful Podman 5.8.2 on an AWS RHEL 9.8 x86_64 PAYG builder.
Application services run rootless on the booted host. No real provider keys
or paid model requests were used.

RHEL base input:

```text
registry.redhat.io/rhel9/rhel-bootc@sha256:cfe6b13fa436d39088cc525254f5de9f4e0c7da8b8f0b44b926acd11cdeb42d7
```

Praxis, OpenShell and harness inputs use the existing repository pins in
`scripts/common/lib.sh` and `openshell/configs/images.env`. The native OpenShell
CLI reports `0.0.116-rhaiv.14`; the sandboxed Codex CLI reports `0.155.1`.
The sandboxed OpenCode CLI reports `1.18.31`.

## Built artifacts

All are in the builder's **rootful** Podman store under
`localhost/secure-single-server`. They have not been published to a registry.
Image IDs identify the configuration independently of archive/manifest format
conversion during transfer.

| Tag | Image ID prefix | Uncompressed size |
| --- | --- | --- |
| `base` | `41e36b93563b` | 2,073,762,211 bytes |
| `codex` | `e63879ead0f4` | 2,073,802,872 bytes |
| `opencode` | `a45b748f5afd` | 2,073,803,386 bytes |
| `openclaw` | `94c2ae833351` | 2,073,803,899 bytes |

The base layers are shared. Each harness adds about 40 KiB, excluding OCI
metadata. Workload containers are fetched separately after boot.

## Checks

- All four builds completed and passed `bootc container lint`: 12 checks passed,
  one skipped, one `/var` layout warning. The warning concerns cloud-init and
  dhclient directories, ldconfig cache and inherited build information; no
  application state or credentials are embedded.
- All four passed `bootc/test-images`, including native CLI execution, enabled
  startup service, absence of RHUI keys and machine secrets, and harness
  argument-validation regression checks.
- Five local build/harness regression tests passed, along with ShellCheck,
  existing gateway static checks and OpenShell policy static checks.
- A disposable RHEL EC2 instance was converted with `bootc install
  to-existing-root`. Bootc reported the selected image; the OS filesystem was
  read-only and SELinux remained enforcing.
- The final Codex deployment passed `bootc/test-host codex` after an OS upgrade
  and reboot. Praxis was healthy with dummy secrets; OpenShell's API was
  reachable; ports 8080, 8081, 8090 and 8091 listened only on loopback.
- The packaged Codex creation script created a `Ready` sandbox. Executing
  `codex --version` over its OpenShell SSH proxy worked. Codex emitted a
  nonfatal warning about creating PATH aliases under the review policy.
- Switching to the final OpenCode image required two new layers (38.4 kB).
  After reboot, `bootc/test-host opencode` passed, the packaged creation script
  created a `Ready` dev sandbox, and `opencode --version` succeeded over its
  SSH proxy. OpenCode's review sandbox reached `Ready`, but CLI startup was
  denied when it tried to create `/sandbox/.local/share`; the read-only policy
  was retained and this profile is not qualified.
- `bootc rollback` followed by a reboot returned to the final Codex image.
  `bootc/test-host codex` passed again, including healthy Praxis using the
  persisted dummy secrets and a reachable OpenShell gateway.

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
previously applied only by bootc. All four images were rebuilt on the same native
AWS RHEL 9 builder and passed `bootc/test-images`. The revised Codex deployment
booted via `bootc upgrade`; host checks passed for read-only root, SELinux
Enforcing, rootless healthy services and loopback-only listeners. Detached
creation without a TTY reached Ready and `codex --version` returned 0.155.1.

Additional review checks:

- All 16 standalone/rendered integrated policy files passed the exact pinned CLI
  parser in a network-disabled container. Numeric ports now survive rendering.
- Five build tests, three harness behavioral tests, 33 existing remote/AWS tests,
  shared-gateway static checks, ShellCheck and OpenShell workflow actionlint passed.
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
network enforcement and real tool tasks remain unqualified. Codex/OpenClaw now
reject integrated `--config`; OpenCode's config path is explicitly experimental.
The runtime workflow is an opt-in qualification gate and will fail while those
network prerequisites are unmet. Existing sandbox deletion/recreation also proved
unreliable during canary testing; retained harness/session claims were removed.

[Review resolution matrix](../openshell/REVIEW-FOLLOWUP.md) maps F01–F10 to changes
and the remaining qualification boundaries.

The final review payload also completed a second upgrade/reboot and passed the
same host checks. The booted Codex OS digest was
`sha256:d89f2ca4fb098f9e568816fb72c035dc3e2c05a152b4c8b86e7f918eec13d801`.
This is a local containers-storage validation digest, not a published registry tag.

## Shared gateway cleanup regression (September 25)

After extracting the shared certificate/configuration/startup helpers, all four
images rebuilt and passed image checks on native AWS RHEL 9 x86_64. Mutable
OpenShell install, reinstall and uninstall passed. Three focused regressions cover
the two startup modes, preserved CLI registration and failed health checks;
build, harness, probe, static, ShellCheck and workflow checks also passed.

The updated Codex image completed a bootc upgrade and reboot. Host checks passed
for read-only root, SELinux Enforcing, rootless healthy services and loopback-only
listeners. A new detached sandbox reached Ready and returned `codex-cli 0.155.1`.
The booted local containers-storage digest was
`sha256:f6434365a7b85d11b9adeb13d912a4622d4a9d3e08fef0181edc2ca4a6590a9a`.
The provider/network qualification gaps above remain unchanged.
