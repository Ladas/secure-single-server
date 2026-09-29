# Deploy two AWS RHEL test VMs

Run these commands from the reviewed checkout **on your workstation**, in the
same Bash or zsh terminal. You need AWS CLI v2, Python 3.9+, `jq`, `curl` and
OpenSSH. Each plan/deploy command handles **one VM**:

- **`all-in-one`**: Praxis, local vLLM hardware, then optional OpenShell on the same VM.
- **`remote-gateway`**: separate HTTPS/JWT gateway; choose inference hardware independently.

This provisions RHEL 9, networking and storage. Service installation follows
in [smoke testing](rhel-smoke.md); [real-provider testing](rhel-real.md) describes
the real vLLM install and optional OpenAI/Anthropic additions.

## 1. Load the current helper

**Repeat this after a checkout update, including in an already-open terminal.**
Shell functions stay in memory until reloaded. This preserves your credentials,
run prefix, SSH key and discovered settings:

```console
source scripts/aws/session.sh || printf 'Load failed; run from the reviewed repository root.\n'
```

**Already entered credentials, discovered networking and created your key?**
Keep those values and skip to step 3. Otherwise, load credentials through the
existing hidden prompts in a private terminal:

```console
aws_test_credentials || printf 'Credentials not loaded; correct the input and retry.\n'
```

## 2. Prepare one new run

Run this block once. On retries keep the same prefix and key. Empty `SUBNET`
selects an existing default public subnet; empty `CLIENT_CIDR` detects your
public IPv4 `/32`. **You do not need to type your IP.**

```console
REGION=eu-central-1
SUBNET=''
CLIENT_CIDR=''
RUN_PREFIX="rhel-$(date -u +%y%m%d-%H%M%S)"
SSH_KEY="$HOME/.secure-single-server-tests/ssh/$RUN_PREFIX"
unset AWS_TEST_READY RHEL_HOST ALL_IN_ONE_HOST REMOTE_GATEWAY_HOST
```

```console
aws_test_discover || printf 'Discovery failed; correct the reported problem and retry.\n'
```

Check the printed AWS account/principal. If needed, set `SUBNET` to an approved
public subnet or `CLIENT_CIDR` to your actual SSH source `/32`, then rediscover.
No VPC or subnet is created. **Discovery does not create an SSH key:**

```console
aws_test_key || printf 'Key not created; resolve the error before planning.\n'
```

Use a passphrase. Only the `.pub` file goes to AWS. Existing keys are never
overwritten: reuse your dedicated test key by setting its absolute `SSH_KEY`
path and skipping creation. Both private and `.pub` files must exist.

## 3. Choose hardware: one block per VM

**Names and roles stay `all-in-one` / `remote-gateway`.** The JSON file selects
hardware; `--scenario` selects the role and networking. Either role can run
with CPU, GPU or no local inference.

Pick **one all-in-one block** and **one remote-gateway block**. These only set
variables; they create nothing. Plan and deploy reuse the same arrays.

### All-in-one: pick one

**GPU vLLM (recommended):** `g6.2xlarge`, one L4, 32 GiB RAM, 200 GiB disk.

```console
ALL_IN_ONE_VM=(configs/aws/vllm-gpu.json --scenario all-in-one)
```

**CPU vLLM:** `m7i.4xlarge`, 64 GiB RAM, 100 GiB disk. Slower inference.

```console
ALL_IN_ONE_VM=(configs/aws/vllm-cpu.json --scenario all-in-one)
```

**No vLLM:** `m7i.2xlarge`, 32 GiB RAM, 50 GiB disk. Mocks/cloud only.

```console
ALL_IN_ONE_VM=(configs/aws/no-vllm.json --scenario all-in-one)
```

### Remote gateway: pick one

**No vLLM (recommended for gateway smoke tests):** `m7i.2xlarge`, 32 GiB RAM,
50 GiB disk. Mocks/cloud only.

```console
REMOTE_GATEWAY_VM=(configs/aws/no-vllm.json --scenario remote-gateway)
```

**Its own GPU vLLM:** `g6.2xlarge`, one L4, 32 GiB RAM, 200 GiB disk.

```console
REMOTE_GATEWAY_VM=(configs/aws/vllm-gpu.json --scenario remote-gateway)
```

**Its own CPU vLLM:** `m7i.4xlarge`, 64 GiB RAM, 100 GiB disk. Slower inference.

```console
REMOTE_GATEWAY_VM=(configs/aws/vllm-cpu.json --scenario remote-gateway)
```

All CPU/GPU presets target Qwen3-8B. A no-vLLM remote-gateway has no real Qwen
backend; sharing all-in-one's model is not configured. OpenShell can later reuse
all-in-one without changing its role. Hardware specifications:
[AWS G6](https://aws.amazon.com/ec2/instance-types/g6/) and
[AWS M7i](https://aws.amazon.com/ec2/instance-types/m7i/).
See [custom settings](aws-operations.md#direct-cli-and-custom-vm-configurations)
for JSON and hardware overrides, or [additional variants](aws-operations.md#deploy-additional-variants-of-a-scenario)
to deploy several VMs with the same role, such as a separate CPU all-in-one.

## 4. Choose access: one block per VM

Apply these **after** the hardware blocks. Pick **one option per VM**; rerunning
a hardware block resets that VM's access overrides. All-in-one exposes only SSH.
Remote-gateway exposes SSH and HTTPS 8443. vLLM, admin, Valkey and OpenShell
control ports stay closed to inbound AWS traffic.

### All-in-one access: pick one

**Detected workstation IP (recommended):** no IP to type.

```console
ALL_IN_ONE_VM+=(--ssh-access restricted)
```

**A specific workstation/VPN IP:** replace the example with your actual public IPv4.

```console
ALL_IN_ONE_VM+=(--ssh-access restricted --allowed-cidr 203.0.113.10/32)
```

**Public SSH:** any IPv4 can reach port 22; SSH authentication is still required.

```console
ALL_IN_ONE_VM+=(--ssh-access public)
```

### Remote-gateway access: pick one

**Detected workstation IP (recommended):** restrict both SSH and HTTPS to that `/32`.

```console
REMOTE_GATEWAY_VM+=(--ssh-access restricted --https-access restricted)
```

**A specific workstation/VPN IP:** restrict both SSH and HTTPS to it; replace the example.

```console
REMOTE_GATEWAY_VM+=(--ssh-access restricted --https-access restricted --allowed-cidr 203.0.113.10/32)
```

**Public SSH, restricted HTTPS:** port 22 is public; HTTPS stays at your detected `/32`.

```console
REMOTE_GATEWAY_VM+=(--ssh-access public --https-access restricted)
```

**Restricted SSH, public HTTPS/JWT endpoint:** SSH stays at your detected `/32`;
any IPv4 can reach HTTPS 8443. Callers still need a valid JWT after gateway installation.

```console
REMOTE_GATEWAY_VM+=(--ssh-access restricted --https-access public)
```

To restrict SSH to a specific workstation/VPN IP with public HTTPS, append
`--allowed-cidr 203.0.113.10/32` inside that block, replacing the example IP.

Public SSH still requires authentication; keep passwords disabled and the host
patched. Access flags change AWS ingress only. The service installer configures
TLS/JWT. Use explicit `public` flags instead of `--allowed-cidr 0.0.0.0/0`.
[SSM Session Manager](aws-operations.md#ssm-session-manager) is not supported
by this provisioning/test workflow.

## 5. Plan each VM separately

All-in-one:

```console
aws_test_plan all-in-one "${ALL_IN_ONE_VM[@]}" \
  || printf 'Plan failed; nothing launched. Correct the error and retry.\n'
```

Remote gateway:

```console
aws_test_plan remote-gateway "${REMOTE_GATEWAY_VM[@]}" \
  || printf 'Plan failed; nothing launched. Correct the error and retry.\n'
```

Each prints **one JSON plan** and makes no changes. With the recommended hardware blocks:

| Name / prefix suffix | Scenario | Inference | Type / disk |
| --- | --- | --- | --- |
| `all-in-one` | `all-in-one` | `gpu` | `g6.2xlarge` / 200 GiB |
| `remote-gateway` | `remote-gateway` | `none` | `m7i.2xlarge` / 50 GiB |

Check the account, subnet/AZ and ingress too. A successful plan confirms the
instance type is offered in that AZ; it does not reserve capacity or prove
GPU quota. See [recovery](aws-operations.md) if a check fails.

## 6. Deploy each VM separately

Each command revalidates and prints its current plan, then asks you to type
`launch ACCOUNT REGION PREFIX`. Run only the VM commands you want:

```console
aws_test_deploy all-in-one "${ALL_IN_ONE_VM[@]}" \
  || printf 'Deploy stopped; inspect the journal and tagged resources before retrying.\n'
```

```console
aws_test_deploy remote-gateway "${REMOTE_GATEWAY_VM[@]}" \
  || printf 'Deploy stopped; inspect the journal and tagged resources before retrying.\n'
```

Each VM has a separate `.state/$RUN_PREFIX-NAME.json` journal. Existing names
and journals are refused. Never delete a journal to bypass recovery.

## 7. Verify, unlock SSH and test

Wait for each VM to be running, then retain its verified login:

```console
unset ALL_IN_ONE_HOST
if aws_test_verify all-in-one; then ALL_IN_ONE_HOST="$RHEL_HOST"; fi
```

```console
unset REMOTE_GATEWAY_HOST
if aws_test_verify remote-gateway; then REMOTE_GATEWAY_HOST="$RHEL_HOST"; fi
```

Connect once to each host and check its SSH fingerprint through a trusted
channel. Return to your workstation after each remote session:

```console
aws_test_ssh all-in-one || printf 'SSH failed; check the address and key.\n'
```

```console
aws_test_ssh remote-gateway || printf 'SSH failed; check the address and key.\n'
```

```console
ssh-add "$SSH_KEY" || printf 'Unlock the key before automated SSH testing.\n'
```

Continue with **[RHEL smoke tests](rhel-smoke.md)**, then
**[real-provider tests](rhel-real.md)** and the
[harness acceptance checklist](harnesses.md). AWS verification does not test
guest drivers or services. Keep these terminal settings; share only login
addresses, SSH key **path**, run prefix and journal paths.

When finished, **terminate** both VMs; stopping retains billable disks.
[Cleanup and partial-launch recovery](aws-operations.md#cleanup) covers the
remaining checks. No AWS resources are deleted automatically.
