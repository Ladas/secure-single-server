# Deploy AWS RHEL test VMs

Start here. Deploy any of the VMs below; each has its own plan, launch
and journal. They can run at the same time. AWS deployment prepares the host;
[smoke tests](rhel-smoke.md) install and test the services afterward.

| VM name | Scenario | Inference preset |
| --- | --- | --- |
| `all-in-one-gpu` | Local users, optional OpenShell | GPU: `g6.2xlarge`, L4, 32 GiB RAM, 200 GiB disk |
| `all-in-one-cpu` | Local users, optional OpenShell | CPU: `m7i.4xlarge`, 64 GiB RAM, 100 GiB disk |
| `remote-gateway-gpu` | Remote HTTPS/JWT clients | GPU: `g6.2xlarge`, L4, 32 GiB RAM, 200 GiB disk |
| `remote-gateway-cpu` | Remote HTTPS/JWT clients | CPU: `m7i.4xlarge`, 64 GiB RAM, 100 GiB disk |
| `all-in-one-cloud` | Local users, external providers only | No vLLM: `m7i.2xlarge`, 32 GiB RAM, 50 GiB disk |
| `remote-gateway-cloud` | Remote clients, external providers only | No vLLM: `m7i.2xlarge`, 32 GiB RAM, 50 GiB disk |

Run these commands from the repository root on your workstation, in Bash or
zsh. Install AWS CLI v2, Python 3.9+, `jq`, `curl` and OpenSSH first.

## 1. Prepare a fresh run

```console
source scripts/aws/session.sh || printf 'Load failed; check your working directory.\n'
aws_test_credentials || printf 'Credentials failed; retry before continuing.\n'
```

Enter AWS credentials at the hidden prompts. Then set up this run:

```console
REGION=eu-central-1
SUBNET=''
CLIENT_CIDR=''
RUN_PREFIX="rhel-$(date -u +%y%m%d-%H%M%S)"
SSH_KEY="$HOME/.secure-single-server-tests/ssh/$RUN_PREFIX"
aws_test_discover || printf 'Discovery failed; correct the error before continuing.\n'
```

Empty `SUBNET` selects an existing default public subnet. Empty `CLIENT_CIDR`
detects your public IPv4 `/32`. Check the printed account, region and subnet.
Create the SSH key with a passphrase, then unlock it:

```console
aws_test_key || printf 'Key creation failed; correct the error before planning.\n'
ssh-add "$SSH_KEY" || printf 'Key not unlocked; retry before SSH testing.\n'
```

Keep `REGION`, `ACCOUNT`, `RUN_PREFIX` and `SSH_KEY` for this run. Only the public
key goes to AWS. For an existing run, use [resume settings](aws-operations.md#resume-a-terminal-or-inspect-an-earlier-vm)
instead of generating a new prefix/key.

## 2. Choose access

Default: restrict SSH and gateway HTTPS to your detected IP:

```console
ALL_IN_ONE_ACCESS=(--ssh-access restricted)
REMOTE_GATEWAY_ACCESS=(--ssh-access restricted --https-access restricted)
```

Optional: keep SSH restricted but allow HTTPS/JWT clients from any IP:

```console
REMOTE_GATEWAY_ACCESS=(--ssh-access restricted --https-access public)
```

Choose access **before** configuring a VM below. [More access examples](aws-operations.md#access-and-changed-ips)
cover public SSH and explicit IPs. Only SSH (22) and remote-gateway HTTPS
(8443) can be opened; vLLM and management ports stay private.

## 3. Deploy the VMs you need

For each chosen VM, run its **plan**, review the one-VM output, then run its
separate **deploy** command. Deployment revalidates the plan and asks for
`launch ACCOUNT REGION PREFIX`. Stop on errors; [inspect a failed launch](aws-operations.md#if-apply-failed)
before retrying. For `InsufficientInstanceCapacity`, use the
[placement check and recovery steps](aws-operations.md#capacity-errors).
Nothing is cleaned up automatically.

The config chooses hardware; `--scenario` chooses the gateway role. To change
hardware or disk size, see [configuration examples](aws-operations.md#direct-cli-and-custom-vm-configurations).

### All-in-one GPU

```console
ALL_IN_ONE_GPU_VM=(configs/aws/vllm-gpu.json --scenario all-in-one "${ALL_IN_ONE_ACCESS[@]}")
aws_test_plan all-in-one-gpu "${ALL_IN_ONE_GPU_VM[@]}" \
  || printf 'Plan failed; correct the error before deploying.\n'
```

```console
aws_test_deploy all-in-one-gpu "${ALL_IN_ONE_GPU_VM[@]}" \
  || printf 'Deploy stopped; inspect its journal before retrying.\n'
```

### All-in-one CPU

```console
ALL_IN_ONE_CPU_VM=(configs/aws/vllm-cpu.json --scenario all-in-one "${ALL_IN_ONE_ACCESS[@]}")
aws_test_plan all-in-one-cpu "${ALL_IN_ONE_CPU_VM[@]}" \
  || printf 'Plan failed; correct the error before deploying.\n'
```

```console
aws_test_deploy all-in-one-cpu "${ALL_IN_ONE_CPU_VM[@]}" \
  || printf 'Deploy stopped; inspect its journal before retrying.\n'
```

### Remote-gateway GPU

```console
REMOTE_GATEWAY_GPU_VM=(configs/aws/vllm-gpu.json --scenario remote-gateway "${REMOTE_GATEWAY_ACCESS[@]}")
aws_test_plan remote-gateway-gpu "${REMOTE_GATEWAY_GPU_VM[@]}" \
  || printf 'Plan failed; correct the error before deploying.\n'
```

```console
aws_test_deploy remote-gateway-gpu "${REMOTE_GATEWAY_GPU_VM[@]}" \
  || printf 'Deploy stopped; inspect its journal before retrying.\n'
```

### Remote-gateway CPU

```console
REMOTE_GATEWAY_CPU_VM=(configs/aws/vllm-cpu.json --scenario remote-gateway "${REMOTE_GATEWAY_ACCESS[@]}")
aws_test_plan remote-gateway-cpu "${REMOTE_GATEWAY_CPU_VM[@]}" \
  || printf 'Plan failed; correct the error before deploying.\n'
```

```console
aws_test_deploy remote-gateway-cpu "${REMOTE_GATEWAY_CPU_VM[@]}" \
  || printf 'Deploy stopped; inspect its journal before retrying.\n'
```

### All-in-one without vLLM

Uses external providers such as OpenAI and Anthropic; no model download or GPU.

```console
ALL_IN_ONE_CLOUD_VM=(configs/aws/no-vllm.json --scenario all-in-one "${ALL_IN_ONE_ACCESS[@]}")
aws_test_plan all-in-one-cloud "${ALL_IN_ONE_CLOUD_VM[@]}" \
  || printf 'Plan failed; correct the error before deploying.\n'
```

```console
aws_test_deploy all-in-one-cloud "${ALL_IN_ONE_CLOUD_VM[@]}" \
  || printf 'Deploy stopped; inspect its journal before retrying.\n'
```

### Remote-gateway without vLLM

Uses HTTPS/JWT to reach external providers; no model download or GPU.

```console
REMOTE_GATEWAY_CLOUD_VM=(configs/aws/no-vllm.json --scenario remote-gateway "${REMOTE_GATEWAY_ACCESS[@]}")
aws_test_plan remote-gateway-cloud "${REMOTE_GATEWAY_CLOUD_VM[@]}" \
  || printf 'Plan failed; correct the error before deploying.\n'
```

```console
aws_test_deploy remote-gateway-cloud "${REMOTE_GATEWAY_CLOUD_VM[@]}" \
  || printf 'Deploy stopped; inspect its journal before retrying.\n'
```

## Share deployed VM details

To hand testing over, copy this block into the same workstation terminal and
paste its output. It lists only this run's deployed VMs and does not print
credentials or private key contents. Keep your SSH key unlocked with `ssh-add`.

```console
(
  printf 'AWS account: %s\nRegion: %s\nRun prefix: %s\n' "$ACCOUNT" "$REGION" "$RUN_PREFIX"
  found=no
  for VM_NAME in all-in-one-gpu all-in-one-cpu remote-gateway-gpu remote-gateway-cpu \
    all-in-one-cloud remote-gateway-cloud; do
    if [ -f "$AWS_TEST_REPO/.state/$RUN_PREFIX-$VM_NAME.json" ]; then
      found=yes
      aws_test_verify "$VM_NAME" || printf 'UNVERIFIED: %s; inspect before testing.\n' "$VM_NAME"
    fi
  done
  if [ "$found" = no ]; then printf 'No deployed VM journals found for this run.\n'; fi
)
```

This leaves your current selection unchanged. Keep the private journals for
recovery. The tester also needs SSH access from the allowed source IP.

## 4. Select one VM for testing

Run **one** of these commands. Repeat this selection whenever you switch VMs:

```console
aws_test_verify all-in-one-gpu || printf 'Verify failed; do not continue to testing.\n'
```

```console
aws_test_verify all-in-one-cpu || printf 'Verify failed; do not continue to testing.\n'
```

```console
aws_test_verify remote-gateway-gpu || printf 'Verify failed; do not continue to testing.\n'
```

```console
aws_test_verify remote-gateway-cpu || printf 'Verify failed; do not continue to testing.\n'
```

```console
aws_test_verify all-in-one-cloud || printf 'Verify failed; do not continue to testing.\n'
```

```console
aws_test_verify remote-gateway-cloud || printf 'Verify failed; do not continue to testing.\n'
```

A successful verify sets `RHEL_HOST`, `RHEL_SCENARIO` and `RHEL_INFERENCE` from
that VM's launch record. All following guides use those three variables and
`SSH_KEY`. No per-host variables or edits to the test commands are needed.
If the VM is still pending, wait and rerun verify. Do not continue after a failure.

Verify the host fingerprint through a trusted channel and connect once:

```console
ssh -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" || printf 'SSH failed; resolve it before testing.\n'
```

Exit the remote shell and continue from your workstation.

## 5. Create the all-in-one user login

Select **one** all-in-one VM in your workstation terminal. Verification sets
`RHEL_HOST` for that VM. Run one block, then the creation block below:

```console
aws_test_verify all-in-one-gpu || printf 'Verify failed; do not create the account.\n'
```

```console
aws_test_verify all-in-one-cpu || printf 'Verify failed; do not create the account.\n'
```

For external providers only:

```console
aws_test_verify all-in-one-cloud || printf 'Verify failed; do not create the account.\n'
```

Repeat selection and creation for each all-in-one VM you deployed. This creates
`praxis-user` before installing Praxis or vLLM, using only this run's public
SSH key. The account has no sudo or service-group membership. Remote-gateway
users run clients on their own machines; skip this step for gateway VMs.

```console
tar --no-xattrs -czf - scripts/common/harness-user scripts/common/harness_user.py \
  scripts/common/harness.py configs/common/harness-versions.json | \
  ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
    'install -d -m 0700 ~/secure-single-server-deploy && tar -xzf - -C ~/secure-single-server-deploy' &&
scp -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" \
  "${SSH_KEY}.pub" "$RHEL_HOST:~/praxis-user.pub" &&
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
  'cd ~/secure-single-server-deploy &&
   sudo dnf module switch-to -y nodejs:22 &&
   sudo dnf install -y nodejs npm git python3 openssh-clients policycoreutils &&
   sudo scripts/common/harness-user --user praxis-user --ssh-public-key "$HOME/praxis-user.pub"' \
  || printf 'User setup failed; inspect the error before continuing.\n'
```

The helper refuses an existing account. If you already created `praxis-user`,
skip creation and log in:

```console
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "praxis-user@${RHEL_HOST#*@}" \
  || printf 'User login failed; check account creation and SSH access.\n'
```

Follow [user setup](../quickstarts/all-in-one/users.md#2-install-the-approved-harnesses)
to install the pinned CLIs in that account. Model requests will work after the
administrator completes service setup below. Exit back to your workstation
before running the test runner; keep `RHEL_HOST` as the administrator login.

## 6. Install services and test

Choose the next guide:

- **CPU/GPU vLLM variants:** [mock smoke tests](rhel-smoke.md), then
  [real Qwen and manual testing](rhel-real.md). OpenShell is optional on all-in-one.
- **External providers only:** on the fresh VM follow the
  [all-in-one installation](../quickstarts/all-in-one/in-memory.md) or
  [remote-gateway installation](../quickstarts/remote-gateway/install.md).
  These guides configure provider credentials without installing vLLM.
  The mock runner can also use this hardware, but its real-Qwen transition
  requires a CPU/GPU inference preset.

When finished, [clean up each VM](aws-operations.md#cleanup).
