# Testing

## AWS RHEL workflow

Use two VMs, with hardware chosen independently for each role:

1. [Deploy all-in-one and remote-gateway](aws.md): choose CPU, GPU or no vLLM;
   plan and deploy each VM separately.
2. [Run mock smoke tests](rhel-smoke.md): install services, exercise native
   harnesses with synthetic credentials, then check reboot behavior.
3. [Install and test real Qwen](rhel-real.md): remove mocks, start private vLLM,
   and optionally add OpenAI and Anthropic to the same Praxis installation.
4. [Create an ordinary SSH login](../quickstarts/all-in-one/accounts.md), then
   [use the harnesses interactively](harnesses.md): copyable commands for
   OpenCode, Codex and Claude Code, including backend compatibility limits.

The [compatibility and test matrix](compatibility.md) records what passed,
what remains untested, known failures and where fixes belong. The
[vLLM debug plan](vllm-debugging.md) covers CPU/GPU isolation and candidate
Praxis/backend updates.

Optional [manual OpenShell testing](openshell-manual.md) reuses all-in-one after
its baseline passes, with administrator setup and ordinary-user commands.
[AWS operations](aws-operations.md) covers custom hardware, recovery and cleanup.
[vLLM administration](vllm.md) covers installation without the smoke runner.

## Local development checks

Run the offline regression suite from the repository root:

```console
python3 -B tests/mocked-provider.py --suite offline
```

It requires Python 3.9+, Bash, Git, OpenSSL, `jq`, `rg`, Ruby with Psych and
ShellCheck. Install zsh to check both supported workstation shells.

With Podman running, execute the container regressions and mock API contracts:

```console
python3 tests/mocked-provider.py --engine podman
```

The [mocked-provider guide](mocked-provider.md) describes suite selection and
coverage. Container tests check startup, credentials, quotas and API contracts;
RHEL tests additionally check packages, SELinux, rootless user services and
reboot behavior. Neither replaces real model/tool acceptance.

Other environments:

- [Fedora CoreOS Podman machine](fedora-coreos.md): the macOS image test loop.
- [Disposable Podman container](podman.md): manual provider calls.
- [Local RHEL VM](rhel-vm.md): the full host test without AWS.
- [Full Fedora VM](fedora-vm.md): development with the explicit Fedora override.

## Architecture and CI

The pinned Praxis and Valkey images include amd64 and arm64. Container tests
compare the image architecture with the engine host; emulation does not qualify
native deployment. The mutable vLLM workflow requires RHEL 9 x86_64.

[CI](../../.github/workflows/validate.yml) runs static checks and container
contracts on native amd64 and arm64 Linux runners with synthetic credentials.
It does not run the RHEL installer or paid provider calls. Qualify each intended
RHEL architecture, profile and harness/model combination separately.

## OpenShell and bootc

These workflows target RHEL 9 x86_64. Run their offline checks on Linux with
Bash 4+ (the macOS system Bash 3.2 cannot run all bootc/static checks):

```console
bash openshell/tests/openshell-static.sh
python3 openshell/tests/probe-test.py
python3 bootc/tests/build.py
shellcheck -x bootc/build bootc/test-images bootc/test-host bootc/scripts/*
```

The OpenShell runtime CI job requires manual dispatch, `OPENSHELL_SELF_HOSTED=true`
and a disposable runner labeled `self-hosted/Linux/X64/rhel9/openshell-disposable`.
A skipped job provides no runtime evidence. For combined Praxis inference, use
[the optional OpenShell smoke step](rhel-smoke.md#optional-openshell).

Follow the [bootc guide](../../bootc/README.md) for image builds and booted host
checks. Bootc and OpenShell lifecycle tests do not qualify all provider/harness
combinations.
