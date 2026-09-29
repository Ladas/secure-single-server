# Real Qwen and optional cloud providers

Complete [mock smoke tests](rhel-smoke.md) on the selected VM first. Run the
commands below from the repository root on your workstation, using
`RHEL_HOST`, `RHEL_SCENARIO`, `RHEL_INFERENCE` and `SSH_KEY` from
[AWS verification](aws.md#4-select-one-vm-for-testing).

Use `--profile valkey` on runner commands if that is the installed profile.

## 1. Install real Qwen

**GPU only:** install the driver, reboot and verify recovery. Skip this block
for CPU VMs.

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --phase gpu-drivers
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --phase lifecycle
```

**Both CPU and GPU:**

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --phase real-setup --inference "$RHEL_INFERENCE"
```

This removes mocks and synthetic cloud secrets, preserves TLS/JWT and Valkey
data, and starts pinned Qwen3-8B as `qwen3-8b`. vLLM has no published host port.
Downloads and CPU startup take several minutes. No cloud key is required.
Qwen thinking is enabled. The [matrix](compatibility.md) records the current
tested stack and results for each setup and harness.

## 2. Test real inference

Start with the API checks and OpenCode file/test task:

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --phase real-test --harness opencode
```

To test reboot recovery, change `real-test` to `real-lifecycle`. To test all
three CLIs, omit `--harness opencode`. All three passed on all-in-one CPU/GPU
vLLM 0.30; limits are recorded in the [compatibility matrix](compatibility.md).
Every failure returns nonzero. Logs are under `.state/rhel-USER-HOST/` on your
workstation and `/var/lib/praxis-rhel-smoke/` on the VM. Real-test JSON records
the deployed image versions, parser/model settings and configuration hashes.
CPU tests automatically allow 60 minutes per CLI; GPU allows 30 minutes.
Result JSON includes elapsed times. See [limits and measured performance](compatibility.md#cpugpu-limits-and-measured-performance)
before comparing the backends.

## 3. Add OpenAI to existing Praxis

To add either optional cloud provider after real setup, first connect as the
administrator:

```console
ssh -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST"
```

For OpenAI, run on the VM (skip this block if adding only Anthropic):

```console
cd ~/secure-single-server-deploy
sudo scripts/common/providers enable openai
```

Enter the key at the hidden prompt. The helper stores it using the stdin-only
Podman secret workflow; users never receive it. Qwen remains available.

## 4. Add Anthropic independently

Optional; works with or without OpenAI. Use the administrator SSH connection
above, even if you skipped the OpenAI enable command:

```console
cd ~/secure-single-server-deploy
sudo scripts/common/providers enable anthropic
sudo scripts/common/providers show
sudo scripts/common/verify --host
```

Repeat `enable` to rotate a key. To disable a route while retaining its secret,
use `sudo scripts/common/providers disable openai` or `disable anthropic`.
Changes preserve other providers and TLS/JWT settings. A service restart resets
memory quotas; Valkey counters persist.

## 5. Start manual testing

Exit any administrator SSH session first. Choose the guide for your scenario:

- **All-in-one:** use the `praxis-user` login created during AWS setup and follow
  [user setup and harness commands](../quickstarts/all-in-one/users.md). If needed,
  [create the account first](../quickstarts/all-in-one/accounts.md).
- **Remote-gateway:** follow [workstation harness testing](harnesses.md#remote-gateway-client).

Run the [file/test acceptance task](harnesses.md#acceptance-task) with each
harness/provider. Provider keys stay in Praxis; users run without sudo.
After the all-in-one baseline, optionally test [OpenShell](openshell-manual.md)
using the authenticated service operator; individual-user enrollment remains
unimplemented. See that guide for the distinction.

For installation without the runner, maintenance or removal, use
[vLLM administration](../quickstarts/common/vllm.md). For another VM, return to
[AWS selection](aws.md#4-select-one-vm-for-testing) and repeat the tests.
