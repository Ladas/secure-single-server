# Real Qwen and optional cloud providers

Start after [mock smoke testing](rhel-smoke.md). Commands use the workstation
variables from [AWS deployment](aws.md): `ALL_IN_ONE_HOST`,
`REMOTE_GATEWAY_HOST` and `SSH_KEY`.

## 1. Install real Qwen

**GPU all-in-one — run on the workstation:**

```console
python3 tests/rhel/run.py --host "$ALL_IN_ONE_HOST" --ssh-key "$SSH_KEY" \
  --scenario all-in-one --phase gpu-drivers
```

Reboot and verify the driver setup with the existing smoke installation:

```console
python3 tests/rhel/run.py --host "$ALL_IN_ONE_HOST" --ssh-key "$SSH_KEY" \
  --scenario all-in-one --phase lifecycle
```

```console
python3 tests/rhel/run.py --host "$ALL_IN_ONE_HOST" --ssh-key "$SSH_KEY" \
  --scenario all-in-one --phase real-setup --inference gpu
```

**CPU remote-gateway — run on the workstation:**

```console
python3 tests/rhel/run.py --host "$REMOTE_GATEWAY_HOST" --ssh-key "$SSH_KEY" \
  --scenario remote-gateway --phase real-setup --inference cpu
```

Use `--profile valkey` on every command if you selected Valkey. Either VM can
use either backend; GPU requires its driver/reboot steps. Downloads and CPU
startup can take several minutes.

`real-setup` removes the test mocks and synthetic cloud secrets, preserves
TLS/JWT identity and Valkey data, and starts pinned Qwen3-8B as `qwen3-8b`.
vLLM has no published host port. No cloud key or replacement VM is required.
The [vLLM images and model revision](../../configs/vllm/images.env) are pinned.

## 2. Test real inference

Run API checks and the OpenCode file/test task:

```console
python3 tests/rhel/run.py --host "$ALL_IN_ONE_HOST" --ssh-key "$SSH_KEY" \
  --scenario all-in-one --phase real-test --harness opencode
```

```console
python3 tests/rhel/run.py --host "$REMOTE_GATEWAY_HOST" --ssh-key "$SSH_KEY" \
  --scenario remote-gateway --phase real-test --harness opencode
```

To test reboot recovery, change `real-test` to `real-lifecycle`.
Omit `--harness opencode` to run all three CLIs; see the
[compatibility and test matrix](compatibility.md). Codex/Claude currently fail
against the pinned real backend; mocks passing does not qualify those paths.
Failures return nonzero. Logs and bundle hashes are saved in
`.state/rhel-USER-HOST/`; detailed CLI logs are under
`/var/lib/praxis-rhel-smoke/` on the VM.

## 3. Add OpenAI to existing Praxis

SSH to the chosen VM and run these commands as its administrator. Complete
`real-setup` before entering real keys.

```console
cd ~/secure-single-server-deploy
sudo scripts/common/providers enable openai
```

Enter the key at the hidden prompt. It goes through the existing stdin-only
Podman secret helper; it is never a command argument, config value or client
credential. Qwen remains available. Choose the OpenAI model when
[starting the harness](harnesses.md#openai).

## 4. Add Anthropic independently

On the chosen VM:

```console
cd ~/secure-single-server-deploy
sudo scripts/common/providers enable anthropic
```

This works with or without OpenAI enabled. Choose the Anthropic model when
[starting the harness](harnesses.md#anthropic).

```console
sudo scripts/common/providers show
sudo scripts/common/verify --host
```

Repeat `enable` to rotate a key. Use `--secret NAME` to activate an existing
versioned secret. Disable a route without deleting its saved secret:

```console
sudo scripts/common/providers disable openai
```

```console
sudo scripts/common/providers disable anthropic
```

Provider changes retain TLS/JWT files and other provider settings. Changes
restart Praxis: memory quotas reset; Valkey counters persist. Repeating an
unchanged selection does not restart it. Modified or mismatched templates are
rejected; failed activation restores the previous configuration.

## 5. Start manual testing

The service/provider commands above are administrator tasks. On all-in-one,
[create a personal SSH login](../quickstarts/all-in-one/accounts.md), then log in as that ordinary user
and follow [manual harness commands](harnesses.md). No sudo is needed to run a
harness. Provider keys stay on the server; local clients use a placeholder and
remote clients use a caller JWT. The same login can run the
[optional OpenShell experiments](openshell-manual.md) after administrator setup.

For installation without the smoke runner, backend diagnostics or removal,
see [vLLM administration](vllm.md).
