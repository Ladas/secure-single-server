# Shared sandbox setup (experimental)

Use a disposable, trusted single-operator RHEL 9 x86_64 host. This is not a
qualified provider/tool-task quickstart. See [validation](../../../bootc/VALIDATION.md)
for the combinations exercised. Select a harness recipe for its limitations:
[Codex](codex.md), [OpenCode](opencode.md), or [OpenClaw](openclaw.md).

On your workstation, clone this repository and transfer/checkout the same revision
on the RHEL VM. On the VM, install the prerequisites in the
[RHEL guide](../../../docs/testing/rhel-vm.md), including Podman, Python 3,
OpenSSH clients, curl and the SELinux management tools. Run from the repository root:

```bash
sudo openshell/scripts/install.sh --owner openshell-svc
```

The owner is a dedicated locked service account with lingering and a user bus.
Run CLI/harness commands as that account, with its HOME and runtime bus:

```bash
harness=codex  # codex, opencode, or openclaw
uid=$(id -u openshell-svc)
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  XDG_RUNTIME_DIR=/run/user/$uid DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$uid/bus \
  "$PWD/openshell/harnesses/$harness/create.sh" --profile dev
```

The checkout and its parent directories must be readable by that account.
On bootc, use `sudo sss-bootc harness create --profile dev` instead.
Creation is detached and returns after structured Ready status; this does not
prove a subsequently launched harness task survives SSH disconnect.

No provider key is forwarded over SSH. Standalone credentials must be explicitly
registered with the pinned CLI's `provider create --credential KEY` environment
lookup and attached with `create.sh --provider NAME`. Use a hidden prompt in the
service-owner environment, never a literal key in shell history or an argument:

```bash
# First import an administrator-reviewed profile matching the pinned binary paths.
# The fresh gateway has no built-in provider profiles.
openshell profile lint -f /path/to/reviewed-openai-profile.yaml
openshell profile import -f /path/to/reviewed-openai-profile.yaml
read -r -s -p 'Synthetic OpenAI test key: ' OPENAI_API_KEY; printf '\n'
export OPENAI_API_KEY
openshell provider create --name test-openai --type openai --credential OPENAI_API_KEY
unset OPENAI_API_KEY
```

Initially use synthetic credentials: actual provider rewriting and real tool tasks
remain unqualified. Do not attach a direct provider in Praxis mode. Codex and
OpenClaw reject `--config`; OpenCode has an experimental Praxis config path.
See [integration status](../../../docs/quickstarts/openshell-praxis/users.md).

Connect with the same owner environment and `connect.sh --name HARNESS-dev`.
Delete with `openshell sandbox delete HARNESS-dev` as that owner. Deleting/recreating a
sandbox does not promise workspace retention; export your work first. Do not source
helper libraries into an interactive shell. `include_workdir` grants filesystem
permissions; it does not mount your checkout or establish persistence.

The dev policy restricts GitHub API methods; Git-over-HTTPS to github.com is not
read-only. Landlock is best-effort and requires inspection of actual runtime
enforcement. See the [threat model](../threat-model.md).
