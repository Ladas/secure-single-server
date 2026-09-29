# AWS VM operations and recovery

Start with the [deployment walkthrough](aws.md). This reference covers the
resource boundary, direct CLI use, recovery and cleanup.

## Resource boundary and permissions

`scripts/aws/rhel-vm` uses AWS CLI v2's credential chain. It creates one
on-demand official Red Hat RHEL 9 PAYG VM, one encrypted gp3 root disk, one
security group and one imported **public** SSH key. The primary interface and
root EBS disk have `DeleteOnTermination=true`. IMDSv2 is required. Resources
carry `ManagedBy`, `ResourcePrefix`, `Scenario` and `Name` tags.

No IAM roles, VPCs, subnets, routes, DNS, SSM access or applications are created.
No AWS/provider credentials enter the VM. There is no user-data bootstrap.
G6's included instance-store NVMe is not formatted or used; model caches and
Podman data belong on the encrypted EBS root disk in the planned installation.

| Mode | Behavior |
| --- | --- |
| `plan` | Read-only validation and resource plan; no state-file writes |
| `apply` | Fresh validation and printed plan, then typed account/region/prefix confirmation before creation |
| `verify` | Read-only comparison against the recorded launch, including ownership, image/type, ingress, IMDSv2 and disk/interface deletion settings |

Credentials need `sts:GetCallerIdentity`, EC2 describe access for instance
types, instance-type offerings, images, subnets, route tables, instances,
security groups, volumes and key pairs. Deployment also needs
`ec2:CreateSecurityGroup`, `ec2:AuthorizeSecurityGroupIngress`,
`ec2:ImportKeyPair`, `ec2:RunInstances` and `ec2:CreateTags` for tagging on
creation. Account policy, RHEL entitlement and service quotas still apply;
planning cannot prove mutation permissions or reserve capacity. No
`iam:PassRole` is needed. Root-account credentials are refused.

## Direct CLI and custom VM configurations

The [session helper](../../scripts/aws/session.sh) manages hidden credential
entry and common workstation settings. The [VM helper](../../scripts/aws/rhel-vm)
plans/applies/verifies exactly one VM. It also works directly with your normal
AWS CLI credential chain; do not mix exported keys and an AWS profile.

```console
python3 scripts/aws/rhel-vm plan --config configs/aws/vllm-gpu.json --scenario all-in-one \
  --region "$REGION" --account-id "$ACCOUNT" --prefix "$RUN_PREFIX-all-in-one" \
  --subnet-id "$SUBNET" --allowed-cidr "$CLIENT_CIDR" \
  --public-key "$SSH_KEY.pub" --state-file ".state/$RUN_PREFIX-all-in-one.json" \
  || printf 'Plan failed; no resources launched.\n'
```

Replace `plan` with `apply` when ready; confirmation remains mandatory. A
separate earlier plan is optional because apply always validates current
inputs. Existing journals, instances, security groups or key pairs with the
same prefix are refused, including partial deployments.

Plan/apply require `--config`. The hardware presets omit `scenario`; pass it with
`--scenario all-in-one` or `--scenario remote-gateway`. The session helper
requires that flag, including for a custom file. JSON accepts `scenario`,
`inference`, `arch`, `instance_type`, `volume_gib`, optional `ami_id` and
`ssh_access` / `https_access` (`restricted` or `public`, both default to
`restricted`). Public HTTPS applies only to `remote-gateway`. Explicit flags
override file values.
Omitted type/disk defaults depend on inference: `none` uses `m7i.2xlarge`
(`m7g.2xlarge` on arm64) / 50 GiB; `cpu` uses `m7i.4xlarge` / 100 GiB;
`gpu` uses `g6.2xlarge` / 200 GiB. Editing inference alone in a complete preset
retains its explicit type/disk, so edit all three or choose the matching preset.
Unknown keys, wrong types, small disks and incompatible architectures fail.

To edit reusable settings without changing a tracked preset, copy a file to
an ignored `*.local` path:

```console
cp -n configs/aws/vllm-gpu.json configs/aws/custom-gpu.local \
  || printf 'Config not copied; inspect the existing file before editing.\n'
```

Edit `instance_type` and `volume_gib` in that file, then use it in the array:

```console
ALL_IN_ONE_VM=(configs/aws/custom-gpu.local --scenario all-in-one)
```

Or append explicit overrides after choosing hardware. These are independent
examples; use only the ones matching your run.

**Larger all-in-one GPU VM:** keep a `vllm-gpu.json` hardware selection.

```console
ALL_IN_ONE_VM+=(--instance-type g6.4xlarge --volume-gib 300)
```

**Larger remote-gateway CPU inference VM:** keep a `vllm-cpu.json` selection.

```console
REMOTE_GATEWAY_VM+=(--instance-type m7i.8xlarge --volume-gib 150)
```

**Another approved subnet for one VM:** replace the example subnet ID.

```console
ALL_IN_ONE_VM+=(--subnet-id subnet-REPLACE_ME)
```

**Pin one official RHEL AMI:** replace the example ID; architecture/owner checks remain.

```console
REMOTE_GATEWAY_VM+=(--ami-id ami-REPLACE_ME)
```

The minimum is 32 GiB RAM for all profiles; CPU inference recommends 64 GiB.
CPU/GPU vLLM profiles require amd64. The current GPU path accepts one full
NVIDIA L4 only, including compatible larger single-L4 instance sizes. It
rejects fractional L4, A10G and multi-GPU types. `none` remains suitable for
arm64 gateway smoke testing when paired with an arm64 instance type.

Planning confirms the instance type is offered in the subnet's Availability
Zone; this does not guarantee spare capacity or sufficient On-Demand GPU quota.
If it fails, select another approved public subnet using `--subnet-id` on that
VM's plan/deploy command. No region, hardware or network fallback is automatic.
AWS metadata does not establish AVX-512 support on the running guest; CPU host
preflight is still required. GPU driver and NVIDIA Container Toolkit readiness
must likewise be checked on the guest before installing vLLM.

## Deploy additional variants of a scenario

The VM name identifies AWS resources and the journal; `--scenario` selects
Praxis's role. Names such as `all-in-one-cpu` and `all-in-one-gpu` both use
`--scenario all-in-one`. Each gets its own VM, security group and journal.
The helper already supports this; hardware never changes the scenario name.

To add CPU all-in-one beside your existing GPU all-in-one and CPU remote-gateway,
use the same prepared workstation terminal, run prefix and SSH key:

```console
source scripts/aws/session.sh
ALL_IN_ONE_CPU_VM=(configs/aws/vllm-cpu.json --scenario all-in-one --ssh-access restricted)
```

```console
aws_test_plan all-in-one-cpu "${ALL_IN_ONE_CPU_VM[@]}" \
  || printf 'Plan failed; nothing launched. Correct the error and retry.\n'
```

```console
aws_test_deploy all-in-one-cpu "${ALL_IN_ONE_CPU_VM[@]}" \
  || printf 'Deploy stopped; inspect its journal before retrying.\n'
```

```console
unset ALL_IN_ONE_CPU_HOST
if aws_test_verify all-in-one-cpu; then ALL_IN_ONE_CPU_HOST="$RHEL_HOST"; fi
aws_test_ssh all-in-one-cpu
```

Check its SSH host key, then exit to the workstation. Unlock the key and run
its smoke and real tests independently:

```console
ssh-add "$SSH_KEY"
python3 tests/rhel/run.py --host "$ALL_IN_ONE_CPU_HOST" --ssh-key "$SSH_KEY" \
  --scenario all-in-one --profile memory
```

```console
python3 tests/rhel/run.py --host "$ALL_IN_ONE_CPU_HOST" --ssh-key "$SSH_KEY" \
  --scenario all-in-one --phase real-setup --inference cpu
```

```console
python3 tests/rhel/run.py --host "$ALL_IN_ONE_CPU_HOST" --ssh-key "$SSH_KEY" \
  --scenario all-in-one --phase real-test --harness opencode
```

The original `ALL_IN_ONE_HOST` and `REMOTE_GATEWAY_HOST` remain available.
Evidence is stored by host, so two VMs with the same scenario do not share logs.
See the [CPU/GPU debug plan](vllm-debugging.md) for the comparisons this enables.

For other combinations, choose a fresh name and array. For example:

```console
REMOTE_GATEWAY_GPU_VM=(configs/aws/vllm-gpu.json --scenario remote-gateway \
  --ssh-access restricted --https-access restricted)
```

```console
aws_test_plan remote-gateway-gpu "${REMOTE_GATEWAY_GPU_VM[@]}"
```

```console
aws_test_deploy remote-gateway-gpu "${REMOTE_GATEWAY_GPU_VM[@]}"
```

Use the same name with verify/SSH. Names accept 1–20 lowercase letters, digits
and hyphens, starting with a letter; the full run-prefix/name must fit 40
characters. Existing names are refused. Record and clean up every extra VM.

## Access and changed IPs

Choose independent SSH/HTTPS settings using the [copyable access blocks](aws.md#4-choose-access-one-block-per-vm).
Discovery detects your workstation's public IPv4 `/32`; use an explicit source
if your VPN or SSH connection has different egress.

For public SSH, check the effective guest settings after a trusted login:

```console
sudo sshd -T | grep -E '^(pubkeyauthentication|passwordauthentication|kbdinteractiveauthentication) '
```

Expect public-key authentication enabled and password/keyboard-interactive
authentication disabled. The AWS helper does not change `sshd` configuration.
AWS recommends restricting [SSH sources](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/changing-security-group.html).

Changing `CLIENT_CIDR` affects new plans only. Manual ingress edits cause
`verify` to report drift; this helper has no security-group update operation.
Use the original/VPN source or clean up and provision with the desired access.

If a plan prints two VMs, reload `source scripts/aws/session.sh` in that terminal,
then plan each role separately. Reloading preserves credentials and run settings.

### SSM Session Manager

SSM is not implemented by this workflow. It requires an SSM Agent, managed-instance
IAM permissions, operator session permissions and access to SSM HTTPS endpoints;
CLI use also needs the Session Manager plugin. See the
[AWS prerequisites](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-prerequisites.html).

SSM shells use IAM authorization; [SSH over SSM](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-getting-started-enable-ssh-connections.html)
also uses the SSH key. This runner requires direct SSH and HTTPS. Adding an IAM
instance profile manually causes the current AWS verifier to report drift.

## Resume a terminal or inspect an earlier VM

Keep the original `REGION`, `ACCOUNT`, `RUN_PREFIX` and `SSH_KEY` with your
non-secret test notes. Reload `source scripts/aws/session.sh` after a checkout
update; this preserves your existing credentials/settings. In a new terminal,
load credentials again and restore those values from the recorded run. Verify
uses the journal, not the current config file or current instance defaults:

```console
aws_test_verify all-in-one || printf 'Verification failed; inspect the recorded deployment.\n'
```

Verify `remote-gateway` independently with `aws_test_verify remote-gateway`.
For any earlier run, use its recorded journal suffix. To inspect one directly:

```console
python3 scripts/aws/rhel-vm verify --region "$REGION" --account-id "$ACCOUNT" \
  --state-file ".state/$RUN_PREFIX-all-in-one.json" \
  || printf 'Verification failed; inspect the journal and tagged resources.\n'
```

After confirmation, apply creates and fsyncs a private recovery journal before
its first mutation. It records the security group, key-pair name, launch client
token and returned instance ID. Failed updates retain the previous record.
Keep these files; never source them as shell code or delete them to bypass a
retry refusal.

## Cleanup

### What costs money, and what termination removes

For this helper's unchanged deployment, **terminate each VM** in the EC2
console to remove its ongoing billable resources. Do not merely stop it:
stopped instances retain billable EBS storage.

| Resource per VM | Charge | On instance termination |
| --- | --- | --- |
| On-demand EC2 instance with RHEL PAYG | Compute and RHEL usage | Instance usage ends |
| One encrypted gp3 root disk, configured size | EBS storage | Deleted (`DeleteOnTermination=true`), including Praxis/Valkey data |
| Auto-assigned public IPv4 | Public IPv4 usage | Released; not an Elastic IP |
| Primary network interface | No separate interface-hour charge | Deleted (`DeleteOnTermination=true`) |
| Security group and imported public SSH key | No ongoing charge | Remain; optional manual housekeeping |

The helper creates **no** NAT gateway, load balancer, Elastic IP, snapshot,
extra data disk or customer-managed KMS key. Internet data transfer and
provider API calls may incur usage charges while testing; termination does
not erase accrued charges. Existing account-level backup/logging policies or
resources you add yourself are outside this helper's cleanup boundary.

The installer keeps its Podman volumes on the VM's root disk; Valkey does not
create another AWS EBS volume. Deleting that disk permanently deletes its data.

AWS documents [instance termination and disk deletion](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/terminating-instances.html),
[public IPv4 release](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-eni.html#eni-basics),
[IPv4 charges](https://aws.amazon.com/vpc/pricing/) and
[security groups without an additional charge](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-security-groups.html).

### Terminate and check

1. Run `verify` before cleanup; it rejects extra disks and retained interfaces.
2. In the EC2 console, select the recorded instance ID and choose
   **Instance state → Terminate (delete) instance**. Repeat for every launched VM.
3. Confirm the instances are terminated, their root volumes and primary
   interfaces are deleted, and their auto-assigned public addresses released.
4. Optionally delete the tagged security groups and imported key pairs.
   Leave shared VPC/subnet resources alone. Revoke provider keys separately.

### If apply failed

Do not delete its journal or immediately launch under a fresh prefix. Inspect
the JSON file and matching resource-prefix tags in the selected account/region.
If `InstanceId` is present, terminate that instance when no longer needed.
If status is `launch-requested` but no instance ID was returned, the launch
may still have succeeded: search EC2 by the resource-prefix tag or the recorded
`ClientToken` before retrying. Inspect tagged EBS volumes too after an
interrupted launch; a volume without a live VM needs separate cleanup.
Earlier failures normally leave only the
non-billable security group/key pair; confirm actual resources in the console.
`verify` refuses an incomplete journal instead of treating it as a successful
deployment. No automatic deletion or launch retry occurs.

```console
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_TEST_CREDENTIALS \
  AWS_TEST_READY RHEL_HOST || printf 'Could not clear credentials; check your shell settings.\n'
```

The helper contains no termination/deletion command. Keep non-secret state
files for audit; never source them as shell code.
