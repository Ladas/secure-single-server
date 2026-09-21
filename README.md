# Secure single-server Praxis

Run one administrator-managed Praxis gateway on a private RHEL 9 server
without giving coding harnesses the upstream provider credentials. Users
sign in with separate OS accounts and reach only host-loopback inference
endpoints.

## Administrator deployment

An administrator starts from a reviewed local checkout, transfers only the
deployment bundle to a private staging directory on RHEL, and installs one
persistent profile. Git and the repository are not required on the server,
and ordinary users do not receive the deployment files.

| Goal | Configuration | Deployment quickstart |
| --- | --- | --- |
| Shared request and token limits held in memory | [`shared-gateway.yaml`](configs/praxis/shared-gateway.yaml) | [In-memory](docs/quickstarts/in-memory.md) |
| Token-limit usage retained across Praxis restarts | [`shared-gateway-valkey.yaml`](configs/praxis/shared-gateway-valkey.yaml) | [Valkey](docs/quickstarts/valkey.md) |
| Administrator-selected Weak/Strong routing for Chat Completions | rendered from [`shared-gateway-switchyard.yaml.in`](configs/praxis/shared-gateway-switchyard.yaml.in) | [Switchyard](docs/quickstarts/switchyard.md) |

The profiles are mutually exclusive. Use the documented uninstall and install
sequence when changing profiles.

Read the [architecture, trust model, limits, and known
gaps](docs/shared-gateway.md) before granting access. The repository scripts
are the current installation mechanism: the quickstarts explain their actions
and provide complete copy-paste commands. A packaged release artifact should
replace the staging-directory transfer in a later release.

## User workflow

After installation, the administrator creates one RHEL account per user,
installs or approves the harness versions, and shares the accepted model IDs.
A user only needs SSH or Session Manager access and the [Claude Code, Codex,
or OpenCode instructions](docs/user-workflow.md). Users do not need the
deployment bundle and cannot operate the Praxis service.

## Development and non-production testing

Repository contributors should start with the [development and testing
guide](docs/testing/README.md).

| Goal | Testing instructions |
| --- | --- |
| Start one disposable Praxis container without installing a service | [Disposable Podman](docs/testing/podman.md) |
| Test images and configuration in the macOS Fedora CoreOS Podman machine | [Fedora CoreOS](docs/testing/fedora-coreos.md) |
| Exercise the installer, systemd, SELinux, account separation, logout, and reboot | [Local RHEL 9 VM](docs/testing/rhel-vm.md) |
| Test Codex, OpenCode, and Claude Code with protected provider keys, in-memory and Valkey profiles | [Harness acceptance](docs/testing/harnesses.md) |

These paths are for development and pre-production validation. They do not
replace final acceptance on the target RHEL server.

## Target hosts and validation status

The persistent deployment targets RHEL 9 on `x86_64` (`linux/amd64`) and
`aarch64` (`linux/arm64`), with SELinux enforcing, cgroups v2, and Podman 4.6
or newer. Both pinned images contain both architectures; the installer rejects
an image that does not match its host.

Native image tests are automated for both architectures. Full RHEL host and
real-provider harness acceptance remain pending on both; image tests alone
do not qualify a production deployment. See the [validation
matrix](docs/testing/README.md#architecture-qualification).
