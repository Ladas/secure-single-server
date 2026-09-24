# Two AWS RHEL test VMs

Create one **all-in-one** VM and one **remote gateway** VM. Use the same
reviewed checkout and image digests as local VM testing. This guide creates
billable resources only when you explicitly run `apply` and confirm each VM.

## What the helper controls

`scripts/aws/rhel-vm` uses AWS CLI v2 and Python 3. It imports a public SSH key,
creates one security group, and launches one official Red Hat RHEL 9 PAYG VM
with a public IPv4 and encrypted 50-GiB gp3 root disk. The disk is deleted on
termination, as is its primary network interface. IMDSv2 is required. The
instance, disk, security group and key pair are tagged by scenario and prefix.

It does not create IAM roles, VPCs, subnets, routes, DNS, SSM access or application
configuration. No AWS/provider credentials enter the VM. Existing resources
with a conflicting prefix are rejected, not adopted or changed. Partial apply
failures leave resources for inspection; there is no automatic cleanup/retry.
After confirmation, `apply` creates and syncs a private recovery journal before
its first AWS mutation. It records the security-group ID, key-pair name, launch
client token and returned instance ID as it proceeds. Invalid state paths fail
before resource creation; failed updates retain the previous journal record.

| Mode | AWS behavior |
| --- | --- |
| `plan` (default) | STS and describe calls only; no resource or state-file writes |
| `apply` | Repeats validation, prints the plan, requires typed account/region/prefix confirmation, then creates the bounded resources |
| `verify` | Read-only check of identity, tags, image, security groups, metadata, and single-disk/interface deletion settings |

Planning validates credentials and the proposed resources, **not** all mutation
permissions or available instance capacity. No universal AWS dry run exists.
Use credentials authorized for the listed EC2 operations in the intended test
account; root-account access keys are refused. No `iam:PassRole` is needed.

## 1. Prepare your workstation and credentials

Start in the reviewed repository checkout on your workstation, with AWS CLI v2,
Python 3.9+, `jq`, `curl` and OpenSSH installed. **Bash and zsh both work; no
shell switch is needed.** Copy one block at a time into the same terminal.
Wait for it to finish before pasting the next block.

The commands below use environment credentials. Environment variables apply
only to this terminal and its child processes; exporting them in a different
terminal does not configure this one. Use a private, unrecorded terminal. Never
put secrets in command arguments, files or shell history.

Load the [session helper](../../scripts/aws/session.sh) and answer its hidden
prompts. Paste each credential only when asked, then press Enter. A blank
required value or Ctrl-D cancels that step without closing your terminal.
Failures leave the terminal open and block dependent deployment steps; correct
the problem and rerun the failed step. These commands do not enable shell
exit-on-error settings or change your shell startup files.

```console
set +x
set +a
if source scripts/aws/session.sh; then
  aws_test_credentials || printf 'Credentials not loaded. Correct the input and rerun this block.\n'
else
  printf 'Run this block from the reviewed secure-single-server repository root.\n'
fi
```

## 2. Use the test defaults

No further AWS settings need typing when your account has a usable default
subnet in Frankfurt. These commands only discover existing resources; they do
not create networking or launch VMs.

| Setting | Default |
| --- | --- |
| Region | `eu-central-1` (Frankfurt) |
| Account | [Discovered from the supplied credentials](https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html); check it against the intended account in your AWS console |
| Network | First available [default subnet](https://docs.aws.amazon.com/vpc/latest/userguide/default-vpc.html) with free addresses, sorted by Availability Zone and subnet ID; the plan must confirm its Internet-gateway route |
| Allowed source | Workstation's detected public IPv4 `/32`, for SSH and remote HTTPS only |
| VMs | Two RHEL 9 PAYG instances, amd64 `m7i.2xlarge`, 32 GiB RAM each |
| Root disks | One encrypted 50-GiB gp3 disk per VM, deleted on termination |
| Resource names | Timestamped run prefix plus scenario name |
| SSH key | New `~/.secure-single-server-tests/ssh/<run-prefix>` key, shared by these two test VMs; separate from your regular `~/.ssh` keys |

Copy unchanged, or edit only this settings block first. Set `ARCH=arm64` for
Graviton `m7g.2xlarge` (also 32 GiB). Set `SUBNET` to an existing approved public
subnet if your account has no default subnet; leave `CLIENT_CIDR` empty for
automatic detection, or set it to your actual SSH/client public IPv4 `/32`.

```console
REGION=eu-central-1
ARCH=amd64
INSTANCE_TYPE=''
SUBNET=''
CLIENT_CIDR=''
RUN_PREFIX="gateway-$(date -u +%y%m%d-%H%M%S)"
SSH_KEY="$HOME/.secure-single-server-tests/ssh/$RUN_PREFIX"
unset AWS_TEST_READY AWS_TEST_PLAN_INPUTS ALL_IN_ONE_HOST REMOTE_HOST
```

Discover the remaining settings (read-only):

```console
aws_test_discover || printf 'Discovery failed. Correct the reported problem and rerun this step.\n'
```

Discovery identifies the account belonging to the keys; it cannot know which
account you intended. Check the printed account/principal before launch. If no
suitable subnet is available, set `SUBNET` to an existing approved public subnet
and rerun discovery; no VPC is created automatically. A VPN or HTTPS proxy can
make IP detection differ from your SSH source. Never widen access to
`0.0.0.0/0`.

## 3. Create the SSH key and plan both VMs

Use a passphrase when `ssh-keygen` prompts. Only the `.pub` file is imported into
AWS; the private key stays in the dedicated testing directory on your
workstation. Nothing is added to `~/.ssh`. Any absolute path in a private
directory works because the SSH commands specify the key with `-i`. Keep keys
outside this repository and shared/cloud-synced directories.

The default directory is private (mode `0700`). The commands refuse to overwrite
either key file, including a symbolic link. For a custom `SSH_KEY`, use a
dedicated parent directory: the helper sets its permissions to `0700`.

```console
aws_test_key || printf 'Key not created. Resolve the error before planning.\n'
```

On a retry, keep the same `RUN_PREFIX` and `SSH_KEY`. If this step already
created your test key, skip key creation and continue to planning; existing
files are never overwritten. Do not rerun the defaults block to recover from
a partial launch: use the recorded state described under cleanup instead.

Plan both VMs without AWS changes or state-file writes:

```console
aws_test_plan || printf 'Plan failed. Nothing launched; correct the error and plan again.\n'
```

The helper checks RAM and architecture through AWS; set `INSTANCE_TYPE` if
the default type is unavailable, then plan again. These CPU-only instances
do not provide CUDA/GPU inference. Local vLLM is a separate hardware test;
32 GiB RAM alone does not establish useful inference performance.

## 4. Launch, inspect and log in

Run only after both plans pass and you have reviewed them. Each VM requires its
own typed account/region/prefix confirmation. A failure stops the sequence;
the other VM is not attempted. Changed settings require a new successful plan.

```console
aws_test_apply || printf 'Apply stopped. Inspect any recorded state and resources before retrying.\n'
```

Wait for both VMs to be running in the EC2 console, then verify and discover
their login addresses (read-only):

```console
aws_test_verify || printf 'Verification incomplete. Read the error; wait for boot if needed, then retry.\n'
```

Connect to the all-in-one VM:

```console
aws_test_ssh all-in-one || printf 'SSH did not complete successfully; your workstation terminal is still open.\n'
```

Leave the **remote SSH session** to return to the workstation before connecting
to the remote gateway. Run the next command on your workstation, not in the VM:

```console
aws_test_ssh remote-gateway || printf 'SSH did not complete successfully; your workstation terminal is still open.\n'
```

Verify SSH host keys through a trusted channel. PAYG RHEL uses cloud-provided
RHUI repositories; do not register it with your Developer Subscription as if
it were the local ISO VM. Check `sudo dnf repolist` before installing packages.

## 5. Install and test separately

| VM | Installation | Harnesses |
| --- | --- | --- |
| All-in-one | [Memory](../quickstarts/all-in-one/in-memory.md), then [Valkey](../quickstarts/all-in-one/valkey.md) | Ordinary RHEL user accounts; loopback endpoints |
| Remote gateway | [Test TLS preparation](remote-gateway.md), then [HTTPS/JWT install](../quickstarts/remote-gateway/install.md) | Mac or another test host; public HTTPS URL, caller JWT and trusted CA |

Return to your workstation before starting either quickstart. Use the printed
login address and SSH key path in its transfer prompts. Store provider keys
through each quickstart's hidden prompts, never through AWS user data.
Run [all three harnesses](harnesses.md) for both quota
profiles. Switchyard is the next round, not part of this acceptance.

## Cleanup

### What costs money, and what termination removes

For this helper's unchanged deployment, **terminate each VM** in the EC2
console to remove its ongoing billable resources. Do not merely stop it:
stopped instances retain billable EBS storage.

| Resource per VM | Charge | On instance termination |
| --- | --- | --- |
| On-demand EC2 instance with RHEL PAYG | Compute and RHEL usage | Instance usage ends |
| One encrypted gp3 root disk, 50 GiB by default | EBS storage | Deleted (`DeleteOnTermination=true`), including Praxis/Valkey data |
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
   **Instance state → Terminate (delete) instance**. Repeat for the other VM.
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
  AWS_TEST_READY AWS_TEST_PLAN_INPUTS || printf 'Could not clear credentials; check your shell settings.\n'
```

The helper contains no termination/deletion command. Keep non-secret state
files for audit; never source them as shell code.
