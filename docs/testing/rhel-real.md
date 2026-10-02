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

**Both CPU and GPU:** choose one model, then run setup.

```console
VLLM_MODEL=qwen3-8b
```

Or test quantized Qwen3.8-27B on the selected host:

```console
VLLM_MODEL=qwen3.8-27b-int4
```

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --phase real-setup --inference "$RHEL_INFERENCE" \
  --model "$VLLM_MODEL"
```

This removes mocks and synthetic cloud secrets, preserves TLS/JWT and Valkey
data, and starts the selected pinned model. The served model ID is the preset
name. vLLM has no published host port. To switch models on this test installation
before adding cloud keys, repeat setup with the other preset; its downloaded
cache is retained. After adding real keys, use the
[administrator installer](../quickstarts/common/vllm.md#3-install-one-backend)
to change models; the test setup refuses real provider credentials.
Downloads and CPU startup take several minutes. No cloud key is required.
Qwen thinking is enabled. The [matrix](compatibility.md) records the current
tested stack and results for each setup and harness.
The 27B preset now serves 32,768 context tokens with an 8,192-token
OpenCode/Claude output budget. Short GPU tool/switching tests passed at these
limits; CPU and near-limit compaction still need qualification. Reapply
setup before testing these limits on an existing test VM. `real-test` refreshes
the shared launcher but does not upgrade the inference service. For a host with
real provider keys, follow [the managed update instructions](../quickstarts/common/vllm.md#update-an-existing-installations-budgets).

## 2. Test real inference

Start with the API checks and OpenCode file/test task:

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --phase real-test --harness opencode
```

To test reboot recovery, change `real-test` to `real-lifecycle`. To test all
three CLIs, omit `--harness opencode`. Tests read the installed model and record
its identity with the results; no `--model` is needed for this phase. Results
and limits are recorded separately for each model in the [compatibility matrix](compatibility.md).
Every failure returns nonzero. Logs are under `.state/rhel-USER-HOST/` on your
workstation and `/var/lib/praxis-rhel-smoke/` on the VM. Real-test JSON records
the deployed image versions, parser/model settings and configuration hashes.
CPU tests automatically allow 60 minutes per CLI; GPU allows 30 minutes.
Result JSON includes elapsed times. See [limits and measured performance](compatibility.md#cpugpu-limits-and-measured-performance)
before comparing the backends.

## 3. Add OpenAI to existing Praxis

After real setup, use [provider administration](../quickstarts/common/providers.md)
from an administrator SSH session. OpenAI, Anthropic and compatible providers
are optional. On all-in-one, enable the shared vLLM quota and unified catalog
there before refreshing user configurations.

```console
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST"
```

Do not rerun mock/real setup after adding real credentials; use the official
installers for maintenance. Provider changes preserve other credentials and
Valkey usage.

## 4. Start manual testing

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
