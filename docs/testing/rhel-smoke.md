# RHEL smoke tests

After [AWS deployment](aws.md#4-select-one-vm-for-testing), select one VM with
`aws_test_verify NAME`. Keep the workstation terminal open: commands below use
`RHEL_HOST`, `RHEL_SCENARIO` and `SSH_KEY`. They work for all four CPU/GPU variants.

The runner installs Praxis and pinned Codex, OpenCode and Claude Code CLIs.
It tests mocked Qwen/vLLM, OpenAI and Anthropic using synthetic credentials.
Services are installed by the administrator; harnesses run as the ordinary
`praxis-smoke` account. No real provider key is needed.

## 1. Install and test

Run from the repository root on your workstation:

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --profile memory
```

This checks JSON/SSE APIs, CLI tool execution and generated tests, then exercises
adding OpenAI and Anthropic independently. Remote-gateway also checks public
TLS/JWT. See the [matrix](compatibility.md) for coverage and exclusions.

Stop on a nonzero result. Rerun the same command after correcting the error;
it resumes its matching mock installation and refuses unrelated installations
or real cloud secrets. GPU drivers are unnecessary for this step.

## 2. Check reboot recovery

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --phase lifecycle
```

This reboots the selected VM, checks its boot ID and repeats host/CLI checks.
Continue to [real Qwen setup](rhel-real.md) when both steps pass.

## Optional Valkey

To test durable quotas, switch the mock installation and repeat lifecycle:

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --profile valkey --phase switch-profile
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --profile valkey --phase lifecycle
```

Retain `--profile valkey` on subsequent commands for this VM.

## Optional OpenShell

On **all-in-one only**, after the native mock suite passes:

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario all-in-one --profile memory --phase openshell
```

Use `--profile valkey` if installed. This checks a sandbox API request and
policy denial; it does not run the CLI file/test task inside OpenShell.
Run this phase before real-provider setup. For actual sandbox harness tasks,
use [manual OpenShell testing](openshell-manual.md) afterward.

## Logs and reruns

Workstation logs: `.state/rhel-USER-HOST/`. VM logs: `/var/lib/praxis-rhel-smoke/`.
Services remain running after a failure. `--phase check` repeats host checks,
`--phase test` repeats baseline mocks/CLIs, and `--phase providers` repeats
provider additions. Keep private state out of Git.
