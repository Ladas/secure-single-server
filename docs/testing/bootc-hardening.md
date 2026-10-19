# Bootc service hardening

> **Where this fits:** Why the bootc reconciler units are not sandboxed, why the
> container units still are, and what was validated on a booted image.

The bootc image runs three oneshot reconciler services. Each one prepares a
workload and then exits:

| Unit | Script | Workload |
| --- | --- | --- |
| `secure-single-server.service` | `bootc/scripts/reconcile` | Praxis and OpenShell |
| `secure-single-server-praxis.service` | `bootc/scripts/praxis` | Standalone Praxis |
| `secure-single-server-vllm.service` | `bootc/scripts/vllm` | Optional vLLM |

All three set `UMask=0077` and deliberately do not set `NoNewPrivileges` or
`PrivateTmp`. Both flags look harmless for a root service that only pulls images
and asks the per-user manager to start containers. On RHEL 9 they each break the
rootless Podman path, as measured on a booted image below. The container units
that these reconcilers write into `/etc/containers/systemd/users/<uid>/` keep
`NoNewPrivileges=true`, and `tests/shared-gateway-static.sh` fails the build when
a rendered container manifest drops it.

## Why `NoNewPrivileges` breaks the reconciler

On RHEL 9, `/usr/bin/newuidmap` and `/usr/bin/newgidmap` carry
`cap_setuid=ep`/`cap_setgid=ep` instead of the setuid bit:

```console
getcap /usr/bin/newuidmap /usr/bin/newgidmap
```

```text
/usr/bin/newuidmap cap_setuid=ep
/usr/bin/newgidmap cap_setgid=ep
```

The kernel ignores file capabilities under `no_new_privs`, so the helpers can no
longer write the subordinate UID/GID map. Every rootless Podman operation that
must enter the full mapping then fails. The reconciler pulls images through
`as_service`/`as_openshell`, which use the full mapping, so its first uncached
pull fails:

```text
newuidmap: write to uid_map failed: Operation not permitted
Error: cannot set up namespace using "/usr/bin/newuidmap": exit status 1
```

A cached image hides the fault because the pull no longer unpacks layers. A fresh
installation always pulls, so the failure is deterministic on first boot.

## Why `PrivateTmp` breaks the reconciler

`PrivateTmp` gives the oneshot a private `/tmp` and `/var/tmp`. The first
rootless Podman call in the unit also creates the service account's *persistent*
rootless network namespace, and that namespace inherits the unit's mount
namespace. When the oneshot exits, systemd deletes the private directories, but
the mounts survive inside the network namespace as deleted dentries:

```text
... /var/tmp ... /var/tmp/systemd-private-...-secure-single-server.service-*/tmp//deleted
... /tmp     ... /systemd-private-...-secure-single-server.service-*/tmp//deleted
```

`pasta` then cannot mount its sandbox tmpfs over `/tmp`, and the user's
containers fail even though the oneshot already exited:

```text
Error: pasta failed with exit code 1:
Failed to mount empty tmpfs for pivot_root(): No such file or directory
Failed to sandbox process, exiting
```

The poisoned namespace is reused for the life of the boot, so removing the flag
requires a reboot (or a network-namespace reset) to take effect.

## Why the container units keep `NoNewPrivileges`

The rendered containers use `--userns keep-id:uid=1001,gid=1001`, which maps only
the invoking account. Podman writes that single-entry map directly, without
`newuidmap`. The rootless network namespace is created by the user manager, not
by a sandboxed oneshot, so no deleted mounts leak in. The container's own
`NoNewPrivileges=true` is what constrains the workload, and it is applied inside
the namespace. Measured on Fedora 42 with rootless Podman 5.7.1 and SELinux
Enforcing:

```console
sudo setpriv --no-new-privs runuser -u "$USER" -- \
  env XDG_RUNTIME_DIR="/run/user/$(id -u "$USER")" \
  podman run --rm --userns keep-id:uid=1001,gid=1001 \
  docker.io/library/alpine:latest id
```

```text
uid=1001(test) gid=1001(1001) groups=1001(1001)
```

Inside that container `NoNewPrivs` reads `1`, and `/proc/self/uid_map` is
byte-identical to the same run without `setpriv`.

## Validated on a booted RHEL 9.8 image

The image was built from the pinned
`registry.redhat.io/rhel9/rhel-bootc@sha256:cfe6b13f...` digest, installed with
`bootc install to-disk` to a spare volume, and booted with UEFI on an AWS
`g6.2xlarge`. The first boot had empty container caches, so every pinned image was
pulled through the reconciler. Results with the flags removed:

```text
Result=success
SubState=exited
reconcile[1181]: OpenShell ready; Praxis awaits provider secrets. See sss-bootc help.
```

The earlier attempts on the same image are the evidence for the two sections
above:

| Unit flags | First boot / activation | Observed |
| --- | --- | --- |
| `NoNewPrivileges=true`, `PrivateTmp=true` | first boot | `newuidmap ... Operation not permitted`, reconciler failed |
| `NoNewPrivileges=false` (drop-in), `PrivateTmp=true` | first boot | reconciler passed; container start failed with the `pasta` `pivot_root` error |
| neither flag | first boot | `OpenShell ready`; dummy secrets activate Praxis, `bootc/test-host` passes |

After activation, `sudo bootc/test-host opencode` checks the rest of the host
contract: SELinux enforcing, read-only `/usr`, healthy Praxis, authenticated
OpenShell gateway on `127.0.0.1:8090/8091`, loopback-only listeners, private
service home directories and `nologin` shells. The `praxis` and `vllm`
reconcilers share the same unit shape but were not exercised on the booted host.

## What still needs confirmation

- A `grep`-based assertion in CI that the three systemd units keep
  `UMask=0077` and do **not** set `NoNewPrivileges` or `PrivateTmp`, and that the
  quadlet templates keep `NoNewPrivileges=true`. Only the rendered container
  manifests are asserted today.
- The SELinux-enforcing lane described in
  [Testing](README.md#local-development-checks); no CI job runs these container
  suites with Podman on an enforcing host, so `:z`/`:Z` mount options are
  currently only exercised as syntax by the Docker-based jobs.
- The optional vLLM and standalone Praxis reconcilers on a booted host.
