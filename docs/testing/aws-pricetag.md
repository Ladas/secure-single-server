# AWS remote gateway with PriceTag

Use this guide to launch two independent RHEL VMs. Both run Praxis, PriceTag
metering/dashboards and PostgreSQL, with no local model weights or GPU. Both
start with SSH and HTTPS restricted to your workstation's public IPv4 `/32`.
The AWS scenario is `remote-gateway`, with inference `none`.

| VM name | Purpose | Upstreams | Initial access |
| --- | --- | --- | --- |
| `pricetag-real` | Real harness use and per-user USD budgets | Real providers with private API-key secrets | Workstation `/32` |
| `pricetag-perf` | Repeatable gateway/accounting load tests | Private synthetic LLM; no real provider keys | Workstation `/32` |

Keep their provider keys, JWT issuers, browser sessions, CA certificates,
databases and client credential directories separate. Never send the synthetic
load test to the real server. After qualifying the real deployment, follow
[opening its HTTPS endpoint](#open-the-real-server-to-any-ip-later) if users
need access from any IP. That step is separate from the initial launch.

## Initial capacity

Use `configs/aws/pricetag-cloud.json`: **m7i.2xlarge, 8 vCPU, 32 GiB RAM,
150 GiB encrypted gp3 root disk**. This is a conservative test candidate for
10–20 concurrent streaming users, not a measured production capacity promise.
The existing VM helper requires at least 32 GiB RAM. AWS lists the hardware in
its [M7i specifications](https://aws.amazon.com/ec2/instance-types/m7i/).

The disk is larger than the ordinary cloud-only preset to accommodate native
image builds, Podman layers, PostgreSQL/WAL, logs and a temporary backup. Do not
interpret it as a retention guarantee. Measure event/index bytes per request
and request volume before setting retention. Keep at least 30% free disk;
store durable encrypted backups off the instance. Termination deletes this root
disk and its database. The default gp3 baseline is 3,000 IOPS and 125 MiB/s;
measure database I/O before buying additional performance.
[AWS gp3 documentation](https://docs.aws.amazon.com/ebs/latest/userguide/general-purpose.html).

Initial service memory ceilings are PostgreSQL 1 GiB, metering 2 GiB, Praxis
1 GiB and mock provider 1 GiB. The host has spare capacity for builds and test
instrumentation. Increase a service ceiling only after measuring pressure;
extra host RAM alone does not change a container's limit. Concurrency is not
requests per second: stream duration, user pauses, dashboard polling and
accounting costs all affect capacity. The public edge retains its 30 requests/s
limit and burst 120; 429s must be reported rather than counted as throughput.

## Launch the two VMs with restricted access

Use the checkout containing this guide. Install AWS CLI v2, Python 3.9+, jq,
curl and OpenSSH on your workstation. Run in Bash or zsh, stopping on any
error. Set up the shared launch session once:

```console
source scripts/aws/session.sh
aws_test_credentials
REGION=eu-central-1
SUBNET=''
CLIENT_CIDR=''
RUN_PREFIX="pricetag-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:8])')"
SSH_KEY="$HOME/.secure-single-server-tests/ssh/$RUN_PREFIX"
aws_test_discover
aws_test_key
ssh-add "$SSH_KEY"
PRICETAG_VM=(configs/aws/pricetag-cloud.json --scenario remote-gateway \
  --ssh-access restricted --https-access restricted)
```

This reuses an administrator SSH key for these two launches; their application
credentials will be generated independently on each VM. Each VM has its own
security group and encrypted root disk. Plan and launch the real server:

```console
aws_test_plan pricetag-real "${PRICETAG_VM[@]}"
```

Review the account, subnet, hardware, disk and `/32` rules, then:

```console
aws_test_deploy pricetag-real "${PRICETAG_VM[@]}"
```

Wait for the recorded instance to reach `running`, then verify:

```console
PRICETAG_INSTANCE=$(jq -er '.InstanceId' \
  ".state/$RUN_PREFIX-pricetag-real.json") &&
  aws --region "$REGION" ec2 wait instance-running --instance-ids "$PRICETAG_INSTANCE" &&
  aws_test_verify pricetag-real
```

Plan and launch the performance server separately:

```console
aws_test_plan pricetag-perf "${PRICETAG_VM[@]}"
```

After reviewing that plan:

```console
aws_test_deploy pricetag-perf "${PRICETAG_VM[@]}"
```

Wait and verify this instance independently:

```console
PRICETAG_INSTANCE=$(jq -er '.InstanceId' \
  ".state/$RUN_PREFIX-pricetag-perf.json") &&
  aws --region "$REGION" ec2 wait instance-running --instance-ids "$PRICETAG_INSTANCE" &&
  aws_test_verify pricetag-perf
```

Launch returns before boot finishes. If verification reports `pending`, the VM
has already been created: run its wait/verify block again, not `aws_test_deploy`.
The [AWS waiter](https://docs.aws.amazon.com/cli/latest/reference/ec2/wait/instance-running.html)
only waits for the EC2 running state; SSH and application readiness are separate
checks. If it fails, inspect the instance state before continuing.

Keep both journals:

```console
REAL_STATE=".state/$RUN_PREFIX-pricetag-real.json"
PERF_STATE=".state/$RUN_PREFIX-pricetag-perf.json"
```

### Show both deployed servers

In the same workstation terminal, with the AWS credentials and launch-session
settings still loaded, run:

```console
printf 'Run prefix: %s\n' "$RUN_PREFIX"
aws_test_verify pricetag-real && aws_test_verify pricetag-perf
```

This prints each instance ID, current state, public IP, hardware, access mode,
SSH login, key path and journal path. It performs read-only AWS checks and does
not print credential values. Share this output with the deployment operator.
The selected `RHEL_HOST` afterwards is the performance VM; explicitly select
the real VM again before working on it. For a new terminal, restore the existing
run using [AWS operations](aws-operations.md); do not generate a new run prefix.

These commands provision infrastructure, not applications. Give the deployment
operator both journal paths, the two public hosts and the SSH key path; never
send private keys or AWS/provider credentials. Verification updates session
variables for the selected VM, so always check the hostname before SSH. Use
[AWS operations](aws-operations.md) for failures, resume settings and cleanup.

Clients connect directly over HTTPS 8443; no SSH tunnels are used. On-VM tests
use HTTPS localhost with the same JWT authentication. PostgreSQL, metering and
mock-provider ports remain private. Both deployments initially restrict the
shared dashboard/inference HTTPS listener to the workstation `/32`.

## Prepare each fresh host

Run this section once for each VM. On the workstation, from this server checkout,
select the destination explicitly before copying files:

```console
VM_NAME=pricetag-real
aws_test_verify "$VM_NAME"
printf 'Destination: %s; SSH key: %s\n' "$RHEL_HOST" "$SSH_KEY"
```

For the second pass set `VM_NAME=pricetag-perf`. Copy the complete required source
directories; the existing-GPU guide's smaller copy command omits the fresh-host
installer, provider templates and performance fixtures:

```console
set -o pipefail
git ls-files -z scripts configs tests | tar --no-xattrs --null -T - -czf - | \
  ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
    'mkdir -p ~/secure-single-server-pricetag && tar -xzf - -C ~/secure-single-server-pricetag'
EXPERIMENTAL_CHECKOUT='/absolute/path/to/reviewed/experimental-checkout'
git -C "$EXPERIMENTAL_CHECKOUT" ls-files -z \
  Cargo.toml Cargo.lock Containerfile LICENSE rust-toolchain.toml crates demos/ai-gateway | \
  tar --no-xattrs -C "$EXPERIMENTAL_CHECKOUT" --null -T - -czf - | \
  ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
    'mkdir -p ~/experimental && tar -xzf - -C ~/experimental'
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST"
```

Replace `EXPERIMENTAL_CHECKOUT` with the reviewed checkout containing
`manual_jwt`. These commands copy tracked/staged source files, not `.state`, Git
metadata or credential directories. Stop if either copy fails. Build images
natively on each RHEL host; do not reuse ARM images from an ARM laptop.

On RHEL, install the base prerequisites and prepare only the service account:

```console
sudo dnf install -y podman git python3 python3-pyyaml openssl policycoreutils-python-utils shadow-utils
cd ~/secure-single-server-pricetag
sudo scripts/common/install --prepare
```

Run this preparation separately on each VM. It creates the locked rootless
service account and user manager without starting the old gateway or its token
limiter. The real-provider path below supplies native provider configuration;
the mock path needs no provider keys or existing gateway configuration.

**Temporary image-build path:** until an image containing `manual_jwt` is
published and its source revision verified, build it manually. Replace this
step with a reviewed immutable registry digest when available; do not assume
an older image or `latest` contains the filter. Metering is unmodified upstream.

In the same RHEL shell, build and load Praxis and unmodified metering. On a fresh
host the source clone below must not already exist. The helper builds its pinned
revision, not the moving repository HEAD:

```console
git clone https://github.com/redhat-et/pricetag-metering.git ~/pricetag-metering
python3 scripts/pricetag/build-metering --source ~/pricetag-metering
podman build --build-arg FEATURES=otel -t localhost/praxis-experimental:manual-jwt \
  -f ~/experimental/Containerfile ~/experimental
PRICETAG_UID=$(id -u praxis-svc)
svc() {
  (cd /tmp && sudo -u praxis-svc env \
    XDG_RUNTIME_DIR="/run/user/$PRICETAG_UID" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$PRICETAG_UID/bus" "$@")
}
set -o pipefail
podman save localhost/pricetag-metering:upstream-557ceb1 | svc podman load
podman save localhost/praxis-experimental:manual-jwt | svc podman load
PRAXIS_IMAGE=$(svc podman image inspect localhost/praxis-experimental:manual-jwt --format '{{.Id}}')
METERING_IMAGE=$(svc podman image inspect localhost/pricetag-metering:upstream-557ceb1 --format '{{.Id}}')
PRAXIS_IMAGE="sha256:${PRAXIS_IMAGE#sha256:}"
METERING_IMAGE="sha256:${METERING_IMAGE#sha256:}"
```

Stop on any build/load failure. Keep these variables and `svc` in the RHEL shell
for the matching installation section below. The `sha256:` normalization handles
Podman versions that omit that prefix from local image IDs. Continue with only
the real-provider or performance section for this host, then client setup.

## Install the real-provider server

Run this section only on `pricetag-real`. Start with one real OpenAI provider;
add other native providers after this path passes. This does not install an
old gateway as a prerequisite. Provider keys and caller JWTs are different:
provider keys stay in service-account Podman secrets; users receive only JWTs.

Enter the provider key at a hidden prompt on RHEL. Shell tracing must be off:

```console
(
set -o pipefail
set +x
set +a
unset PRICETAG_OPENAI_KEY
sudo -v &&
printf 'OpenAI API key: ' &&
IFS= read -r -s PRICETAG_OPENAI_KEY &&
printf '\n' &&
printf '%s' "$PRICETAG_OPENAI_KEY" | sudo scripts/common/secret-set openai v1
)
```

Stop on an error. To rotate later, create a new version and update only the
new gateway's secret reference; do not overwrite an existing secret. Podman
secrets protect against ordinary users, but the host administrator can access
them. Do not use `scripts/common/providers enable` against this standalone
PriceTag installation: that helper manages the older gateway deployment.

Choose an upstream model actually available to the account, with reviewed
context/output limits and a matching PriceTag pricing entry. These are
non-secret values. The following creates inputs, without starting a listener:

```console
install -d -m 0700 "$HOME/pricetag-real-inputs"
printf 'OpenAI model ID: '
IFS= read -r PRICETAG_MODEL
printf 'Reviewed context window: '
IFS= read -r PRICETAG_CONTEXT
printf 'Reviewed maximum output: '
IFS= read -r PRICETAG_OUTPUT
export PRICETAG_MODEL PRICETAG_CONTEXT PRICETAG_OUTPUT
python3 - <<'PYINPUTS'
import json, os, sys
from pathlib import Path
import yaml
sys.path.insert(0, "scripts/common")
from unified_config import validate
source = yaml.safe_load(Path('configs/all-in-one/shared-gateway.yaml').read_text())
model = os.environ['PRICETAG_MODEL'].strip()
context = int(os.environ['PRICETAG_CONTEXT'])
output = int(os.environ['PRICETAG_OUTPUT'])
models = [{'id': 'openai/' + model, 'provider': 'openai', 'model': model,
           'apis': ['openai'], 'context': context, 'output': output}]
models = validate(models)
folder = Path.home() / 'pricetag-real-inputs'
for name, value in [('providers.json', source), ('models.json', models), ('prices.json', {})]:
    with (folder / name).open('x') as file:
        json.dump(value, file, indent=2)
PYINPUTS
```

The source template contains legacy quota definitions, but the PriceTag renderer
removes them and installs external metering. The catalog enables only OpenAI,
so no Anthropic secret or route is enabled. A missing model price stops startup;
review `prices.json` to map the gateway alias to a different explicitly chosen
pricing entry if necessary. Do not silently substitute a guessed price.

Create a secret-reference input and the private network Quadlet. This reference
file contains no secret value and is not installed as a running service:

```console
printf '%s\n' '[Container]' \
  'Secret=praxis-openai-api-key-v1,type=env,target=OPENAI_API_KEY' \
  > "$HOME/pricetag-real-inputs/provider-secrets.container"
PRICETAG_UID=$(id -u praxis-svc)
sudo install -m 0644 configs/common/quadlet/praxis.network \
  "/etc/containers/systemd/users/$PRICETAG_UID/praxis.network"
```

Continue with the selected real server's hostname:

```console
GATEWAY_HOST='REPLACE_WITH_REAL_SERVER_PUBLIC_IP_OR_DNS'
sudo python3 scripts/pricetag/prepare.py \
  --hostname "$GATEWAY_HOST" --praxis-image "$PRAXIS_IMAGE" \
  --metering-image "$METERING_IMAGE" \
  --providers "$HOME/pricetag-real-inputs/providers.json" \
  --models "$HOME/pricetag-real-inputs/models.json" \
  --provider-unit "$HOME/pricetag-real-inputs/provider-secrets.container" \
  --price-sources "$HOME/pricetag-real-inputs/prices.json" --monthly-usd 5
```

Review `/etc/praxis-pricetag/quadlets`, `models.json` and `bootstrap.sql`, then:

```console
sudo scripts/pricetag/start
```

The running gateway has USD enforcement and PriceTag's retained 10-billion-token
monthly safety net, with no Praxis token-rate limiter. For another real provider,
add its native API cluster, HTTPS authority/SNI, credential-injection environment
variable, matching Podman secret reference, model catalog entries and reviewed
prices. Do not assume every provider supports both OpenAI and Anthropic APIs.
Keep such changes in the PriceTag deployment and preserve its database/issuer;
first-time preparation refuses existing directories.

## Install the performance server

Run this section only on `pricetag-perf`. Its mock mode is independent of the
real-provider configuration and does not mount real provider secrets.
Choose this VM's public IP/DNS name:

```console
GATEWAY_HOST='REPLACE_WITH_THIS_VM_PUBLIC_IP_OR_DNS'
printf '%s\n' '{"demo-model":"Qwen3.8-27B-FP8"}' > ~/pricetag-mock-prices.json
sudo python3 scripts/pricetag/prepare.py --mock-provider \
  --hostname "$GATEWAY_HOST" --praxis-image "$PRAXIS_IMAGE" \
  --metering-image "$METERING_IMAGE" --price-sources "$HOME/pricetag-mock-prices.json" \
  --monthly-usd 5
```

The source price is a synthetic chargeback reference, not a real provider bill.
Review `/etc/praxis-pricetag/quadlets` and the catalog: only `demo-model` should
appear. The private fixture supports native Chat, Responses and Messages and
defaults to a one-second delay between SSE events. Its control listener remains
container loopback. It is a test fixture, not an inference service.

```console
sudo scripts/pricetag/start
```

## Client access and qualification

Run on each RHEL VM after startup. Preparation already created Alice's initial
JWT; link that subject to a person and rotate it before distributing credentials:

```console
cd ~/secure-single-server-pricetag
sudo python3 scripts/pricetag/user --subject alice --name Alice --rotate \
  --monthly-usd 5 --output /root/pricetag-admin/alice-ready.jwt
sudo python3 -c 'import json; print("\n".join(m["id"] for m in json.load(open("/etc/praxis-pricetag/models.json"))))'
```

Record the real model alias printed above (`openai/` plus the selected model ID).
The performance server advertises only `demo-model`. Raw JWT issuance alone does
not create the person relationship required for individual overrides. Use
[the credential administration guide](pricetag.md#administrator-scripts-provision-rotate-and-revoke)
for new users, further rotations and revocation. Use a new output filename for
each rotation; preparation and token issuance refuse to overwrite existing state.

Back on the workstation, from this checkout and with the AWS session restored,
select the host again. Use a distinct client directory for each VM:

```console
VM_NAME=pricetag-real
aws_test_verify "$VM_NAME"
CLIENT_DIR="$HOME/.config/praxis-pricetag/$RUN_PREFIX-$VM_NAME"
install -d -m 0700 "$CLIENT_DIR"
umask 077
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
  'sudo -n cat /etc/praxis-pricetag/ca.pem' > "$CLIENT_DIR/ca.pem"
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
  'sudo -n cat /root/pricetag-admin/alice-ready.jwt' > "$CLIENT_DIR/caller.jwt"
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
  'sudo -n cat /root/pricetag-admin/admin.jwt' > "$CLIENT_DIR/admin.jwt"
chmod 0600 "$CLIENT_DIR/caller.jwt" "$CLIENT_DIR/admin.jwt"
GATEWAY_URL="https://${RHEL_HOST#*@}:8443"
```

Complete the preview below for the selected real server first. Later repeat this
client section with `VM_NAME=pricetag-perf` and `MODEL_ALIAS=demo-model`. Stop on
any SSH/copy error.
If preparation used a DNS hostname instead of the IP, set `GATEWAY_URL` to that
exact HTTPS hostname and port. Never copy issuer/CA signing keys. Admin JWTs are
for dashboard administration, not harnesses or budget-denial tests.

On the real VM's client setup, choose its actual model alias and preview:

```console
MODEL_ALIAS='openai/REPLACE_WITH_SELECTED_MODEL_ID'
python3 scripts/pricetag/harness opencode --url "$GATEWAY_URL" \
  --token-file "$CLIENT_DIR/caller.jwt" --ca-file "$CLIENT_DIR/ca.pem" \
  --model "$MODEL_ALIAS" --print-config
```

Remove `--print-config` to launch an installed OpenCode. Run the helper by absolute
path from the project you want to work on so OpenCode keeps that working directory.
For the performance server use `MODEL_ALIAS=demo-model` and preview only: the mock
cannot perform useful coding work. On-VM harnesses use `https://localhost:8443`
with that same VM's CA/JWT; no additional public-IP ingress rule is needed.

Trust the appropriate CA in your browser separately from CLI trust. Open
`$GATEWAY_URL/login` and paste `caller.jwt` for usage, or use a separate browser
profile with `admin.jwt` and open `$GATEWAY_URL/admin#quotas` for budgets. JWTs
have no automatic expiry; existing browser cookies can survive JWT revocation
for seven days. No SSH tunnel is needed.

First verify invalid JWT rejection, private-route isolation, user/admin access,
USD denial, revocation and accounting persistence. Keep both IP-bound during
this qualification. On the performance VM only, follow
[the performance procedure](pricetag-perf.md) for distinct users, staged load,
stream completion and exact database reconciliation.

Measure at 1, 5, 10 and 20 active users. Report successful completions, errors,
latency percentiles, time to first response byte, CPU/RAM and database growth.
Run a short smoke test before a longer soak. Repeat with the load generator on
a separate client to separate generator CPU from gateway capacity; IP-bound
access still applies. A local Podman result does not qualify RHEL capacity.

Keep the performance VM synthetic so repeated tests do not spend real provider
budgets. Add real providers or a private remote vLLM to the real VM only after
reviewing native API support and model pricing.


## Open the real server to any IP later

Keep the initial deployment restricted. Run this section only after the real
server passes client and authorization checks and you choose to allow users
from any IPv4 address. The performance server stays restricted.

The endpoint remains **HTTPS on port 8443**. Opening the security-group rule
removes the source-IP restriction; it does not remove inference JWT validation,
dashboard login, admin authorization, Origin checks or USD enforcement.
Inference, user dashboards and the admin dashboard currently share this port:
**the admin login/routes will also be reachable from any IPv4 address**, with
PriceTag enforcing the authenticated role. A security group cannot distinguish
URL paths. If admin access must remain IP-restricted, implement and test a
separate application/listener boundary before opening this shared listener.

Non-expiring JWTs still require manual revocation/rotation. Existing browser
cookies can survive JWT revocation for seven days; global session-secret
rotation is the available emergency logout for all browsers. Retain the
request-rate limit, review service errors and maintain encrypted backups.

### TLS and hostname

For ordinary browser users, obtain a publicly trusted server certificate for
the public hostname. Prefer choosing that DNS name at initial preparation:
it is included in both the certificate and the dashboard's explicit allowed
Origins. DNS/certificate issuance and automatic renewal are operator-managed;
this deployment does not provision them. A private test CA can remain for
managed clients that explicitly trust it, but opening ingress does not make
browsers trust that CA automatically.

If replacing the laboratory certificate on RHEL, validate the new chain/key,
check that it covers `GATEWAY_HOST`, then install them and restart Praxis using the `svc` function from image
loading:

```console
sudo scripts/remote-gateway/credentials check-tls \
  --cert /root/pricetag-tls/fullchain.pem --key /root/pricetag-tls/privkey.pem
sudo openssl x509 -in /root/pricetag-tls/fullchain.pem -noout -checkhost "$GATEWAY_HOST"
sudo install -o root -g praxis-svc -m 0640 /root/pricetag-tls/fullchain.pem \
  /etc/praxis-pricetag/gateway/tls.pem
sudo install -o root -g praxis-svc -m 0640 /root/pricetag-tls/privkey.pem \
  /etc/praxis-pricetag/gateway/tls-key.pem
sudo restorecon -R /etc/praxis-pricetag/gateway
svc systemctl --user restart pricetag-gateway
```

The hostname check above is for a DNS name; IP certificates need the
corresponding IP SAN check. Back up the existing pair privately before changing
it. Arrange for renewal to update both files and restart the gateway. If the
public hostname changes, also update `manual_jwt` dashboard `allowed_origins`
in `gateway.json` to the new exact `https://HOST:8443` origin and restart.
Keep `https://localhost:8443` for on-host administration. Update clients to the
new URL and certificate trust; the user JWT issuer/audience do not change.

### Change only the real VM's HTTPS rule

Run on the workstation with the launch session restored and AWS credentials
loaded. Additional IAM permission `ec2:ModifySecurityGroupRules` is needed.
Changing the launch array to `--https-access public` does not update an existing
VM, and `scripts/aws/https-access` only supports restricted `/32` additions.
Use the existing rule's ID for this transition.

Verify the real VM against its journal and retain a recovery copy:

```console
aws_test_verify pricetag-real
REAL_STATE=".state/$RUN_PREFIX-pricetag-real.json"
cp -n "$REAL_STATE" "$REAL_STATE.before-public"
REAL_SG=$(jq -er '.SecurityGroupId' "$REAL_STATE")
REAL_HTTPS_RULE=$(aws ec2 describe-security-group-rules --region "$REGION" \
  --filters "Name=group-id,Values=$REAL_SG" --output json | \
  jq -er '[.SecurityGroupRules[] | select(.IsEgress == false and .IpProtocol == "tcp"
    and .FromPort == 8443 and .ToPort == 8443 and .CidrIpv4 != null)] |
    if length == 1 then .[0].SecurityGroupRuleId else error("Expected exactly one IPv4 HTTPS rule") end')
printf 'Real server security group: %s; HTTPS rule: %s\n' "$REAL_SG" "$REAL_HTTPS_RULE"
```

Stop on any verification/query error. Confirm these are the **real** server's
resources before running the mutation:

```console
HTTPS_CIDR=0.0.0.0/0
HTTPS_ACCESS=public
aws ec2 modify-security-group-rules --region "$REGION" --group-id "$REAL_SG" \
  --security-group-rules \
  "SecurityGroupRuleId=$REAL_HTTPS_RULE,SecurityGroupRule={IpProtocol=tcp,FromPort=8443,ToPort=8443,CidrIpv4=$HTTPS_CIDR}" \
  --no-cli-pager
```

This changes only the selected TCP 8443 rule. SSH remains restricted and the
performance VM's security group is untouched. This is IPv4 access; no IPv6
listener/ingress rollout is included.
[AWS rule modification reference](https://docs.aws.amazon.com/cli/latest/reference/ec2/modify-security-group-rules.html).

After AWS reports success, reconcile the real VM's local journal. The following
checks the entire observed ingress against the expected new state before
saving it with the existing atomic journal writer:

```console
python3 - "$REAL_STATE" "$REGION" "$HTTPS_CIDR" "$HTTPS_ACCESS" <<'PYJOURNAL'
import copy, importlib.machinery, importlib.util, ipaddress, json, sys
from pathlib import Path
loader = importlib.machinery.SourceFileLoader('rhel_vm', 'scripts/aws/rhel-vm')
spec = importlib.util.spec_from_loader(loader.name, loader)
vm = importlib.util.module_from_spec(spec)
loader.exec_module(vm)
path, region, cidr, access = sys.argv[1:]
state = json.loads(Path(path).read_text())
assert state['Region'] == region and state['Scenario'] == 'remote-gateway'
network = ipaddress.ip_network(cidr, strict=True)
assert network.version == 4 and ((access == 'public' and cidr == '0.0.0.0/0') or
                                (access == 'restricted' and network.prefixlen == 32))
desired = copy.deepcopy(state)
rules = [r for r in desired['Ingress'] if r.get('IpProtocol') == 'tcp'
         and r.get('FromPort') == 8443 and r.get('ToPort') == 8443]
assert len(rules) == 1
rules[0]['IpRanges'] = [{'CidrIp': cidr}]
desired['HttpsAccess'] = access
aws = vm.Aws(region, None, False)
vm.check_identity(aws, state['AccountId'])
groups = aws.call('ec2', 'describe-security-groups', group_ids=[state['SecurityGroupId']])['SecurityGroups']
assert len(groups) == 1
vm.check_owned(groups[0], state)
vm.check_ingress(groups[0], desired)
vm.save_state(Path(path), desired)
print('Observed ingress verified; real-server journal updated.')
PYJOURNAL
aws_test_verify pricetag-real
aws_test_verify pricetag-perf
```

If reconciliation fails, the AWS rule may already be public. Inspect the
reported mismatch and reconcile or roll back; do not relaunch or edit the
journal to hide unrelated drift. Verify from a second client outside the old
`/32`: HTTPS login loads, unauthenticated inference returns 401, a valid caller
can infer and view their own usage, and an ordinary user cannot administer
budgets. Browser writes require the configured exact public Origin.

### Restore restricted access

Use the same real security group and HTTPS rule ID. Recover the original
workstation CIDR from the saved journal, then modify that rule back:

```console
HTTPS_CIDR=$(jq -er '.Ingress[] | select(.FromPort == 8443) | .IpRanges[0].CidrIp' \
  "$REAL_STATE.before-public")
HTTPS_ACCESS=restricted
aws ec2 modify-security-group-rules --region "$REGION" --group-id "$REAL_SG" \
  --security-group-rules \
  "SecurityGroupRuleId=$REAL_HTTPS_RULE,SecurityGroupRule={IpProtocol=tcp,FromPort=8443,ToPort=8443,CidrIpv4=$HTTPS_CIDR}" \
  --no-cli-pager
```

Rerun the journal-reconciliation block with these variables, then verify both
VMs again. If your workstation IP changed, choose its current public `/32`
explicitly instead. No change to JWTs, TLS or spending records is needed when
changing only the source-IP policy.
