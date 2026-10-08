# AWS remote gateway with PriceTag

Use this guide for a fresh real-provider RHEL VM and an optional, separate
performance VM. Both run Praxis, PriceTag
metering/dashboards and PostgreSQL, with no local model weights or GPU. Both
start with SSH and HTTPS restricted to your workstation's public IPv4 `/32`.
The AWS scenario is `remote-gateway`, with inference `none`.

Follow the sections in order: launch → copy source → prepare host/images →
configure providers → start services → provision users → browser/OpenCode.
Blocks are labelled by machine. Stop at the first failed command. The performance
VM sections are optional; do not run them when you only need the real gateway.
AWS administrator commands run only in your own workstation terminal. Never copy
AWS credentials onto a VM or give them to a deployment assistant.

| VM name | Purpose | Upstreams | Initial access |
| --- | --- | --- | --- |
| `pricetag-real` | Real harness use and per-user USD budgets | Real providers with private API-key secrets | Workstation `/32` |
| `pricetag-perf` | Repeatable gateway/accounting load tests | Private synthetic LLM; no real provider keys | Workstation `/32` |

Keep their provider keys, JWT issuers, browser sessions, CA certificates,
databases and client credential directories separate. Never send the synthetic
load test to the real server. After qualifying the real deployment, follow
[opening its HTTPS endpoint](#open-the-real-server-to-any-ip-later) if users
need access from any IP. That step is separate from the initial launch.

<details>
<summary>Instance sizing, disk and service limits</summary>


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

</details>

## 1. Launch the real VM — AWS admin workstation

Use a normal clone of `redhat-et/secure-single-server` on the branch you intend
to deploy (`main` after merge, or the fetched PR branch while reviewing).
Replace the checkout path in the first block. Install AWS CLI v2, Python 3.9+, jq,
curl and OpenSSH on your workstation. Run in Bash or zsh, stopping on any
error. From this checkout, set up the launch session once:

```console
cd /absolute/path/to/secure-single-server
SERVER_CHECKOUT="$(git rev-parse --show-toplevel)"
cd "$SERVER_CHECKOUT"
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

<details>
<summary>Optional: launch the separate performance VM</summary>

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

</details>

Launch returns before boot finishes. If verification reports `pending`, the VM
has already been created: run its wait/verify block again, not `aws_test_deploy`.
The [AWS waiter](https://docs.aws.amazon.com/cli/latest/reference/ec2/wait/instance-running.html)
only waits for the EC2 running state; SSH and application readiness are separate
checks. If it fails, inspect the instance state before continuing.

Keep the real-server journal (and the performance journal if launched):

```console
REAL_STATE=".state/$RUN_PREFIX-pricetag-real.json"
PERF_STATE=".state/$RUN_PREFIX-pricetag-perf.json"
```

### Show both deployed servers

In the same workstation terminal, with the AWS credentials and launch-session
settings still loaded, run:

```console
printf 'Run prefix: %s\n' "$RUN_PREFIX"
aws_test_verify pricetag-real
if [ -f ".state/$RUN_PREFIX-pricetag-perf.json" ]; then
  aws_test_verify pricetag-perf
fi
```

This prints each instance ID, current state, public IP, hardware, access mode,
SSH login, key path and journal path. It performs read-only AWS checks and does
not print credential values. Share this output with the deployment operator.
If both were checked, `RHEL_HOST` afterwards points to the performance VM; explicitly select
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

## 2. Select the host and copy source — workstation

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
(
set -o pipefail
git ls-files -z scripts configs tests | tar --no-xattrs --null -T - -czf - | \
  ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
    'mkdir -p ~/secure-single-server-pricetag && tar -xzf - -C ~/secure-single-server-pricetag'
) &&
printf '%s\n' "${RHEL_HOST#*@}" | \
  ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
    'umask 077; cat > ~/pricetag-gateway-host'
```

After a successful copy, open a second workstation terminal for SSH. Reuse the
printed key/host values there, or connect from this terminal and keep it open
while running RHEL steps:

```console
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST"
```

The source command copies tracked/staged files, including pending changes in this
checkout, but excludes `.state`, Git metadata and credential directories. Before
merge, use the reviewed PR checkout on both the workstation and VM. Stop if the
copy fails. Build images natively on RHEL; ARM laptop images do not qualify x86_64.
The copy also saves this VM's public IP in `~/pricetag-gateway-host` for TLS
and dashboard Origin configuration. If clients will use DNS, replace that value
with the intended DNS name before preparation.

## 3. Prepare the host and images — RHEL

Install base prerequisites and prepare only the service account:

```console
sudo dnf install -y podman git python3 python3-pyyaml openssl policycoreutils-python-utils shadow-utils &&
cd ~/secure-single-server-pricetag &&
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
git clone https://github.com/praxis-proxy/experimental.git ~/experimental &&
  git -C ~/experimental fetch origin pull/46/head &&
  git -C ~/experimental checkout --detach 8b435909da436e498dc8ffcd1c69b0ecb6896880
```

Build unmodified metering, then Praxis; stop if either build fails:

```console
git clone https://github.com/redhat-et/pricetag-metering.git ~/pricetag-metering &&
python3 scripts/pricetag/build-metering --source ~/pricetag-metering &&
podman build --build-arg FEATURES=otel -t localhost/praxis-experimental:manual-jwt \
  -f ~/experimental/Containerfile ~/experimental
```

Load both images into the service account and record their immutable IDs:

```console
PRICETAG_UID=$(id -u praxis-svc)
svc() {
  (cd /tmp && sudo -u praxis-svc env \
    XDG_RUNTIME_DIR="/run/user/$PRICETAG_UID" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$PRICETAG_UID/bus" "$@")
}
set -o pipefail
podman save localhost/pricetag-metering:upstream-557ceb1 | svc podman load &&
podman save localhost/praxis-experimental:manual-jwt | svc podman load &&
PRAXIS_IMAGE=$(svc podman image inspect localhost/praxis-experimental:manual-jwt --format '{{.Id}}') &&
METERING_IMAGE=$(svc podman image inspect localhost/pricetag-metering:upstream-557ceb1 --format '{{.Id}}') &&
PRAXIS_IMAGE="sha256:${PRAXIS_IMAGE#sha256:}" &&
METERING_IMAGE="sha256:${METERING_IMAGE#sha256:}"
```

Stop on any build/load failure. Keep these variables and `svc` in the RHEL shell
for the matching installation section below. The `sha256:` normalization handles
Podman versions that omit that prefix from local image IDs. Continue with only
the real-provider or performance section for this host, then client setup.

## 4. Configure providers and start the real gateway — RHEL

Run on **RHEL, pricetag-real only**. This is fresh installation, not an upgrade.
The repository helper creates inputs under `/root/pricetag-provider-inputs` and
stores provider keys as versioned rootless Podman secrets. Root administrators
can access secrets; ordinary users receive only their own gateway JWT.

### Configure direct OpenAI

Review the non-secret presets in `configs/pricetag/provider-models.json`, then
run this block. Skip it for a PriceTag-only gateway:

```console
cd ~/secure-single-server-pricetag
sudo python3 scripts/pricetag/providers openai --debug
```

Paste the OpenAI key at the hidden prompt. The helper checks `/v1/models` over
verified HTTPS and enables only advertised preset IDs. It never prints the key
or provider error bodies. The presets are Mini, Luna and Sol, with limits recorded
in the preset file; they are not an assertion that every account has access.

### Optional: add a remote PriceTag inference provider

This upstream is separate from the PriceTag metering service being installed.
Skip this block for an OpenAI-only gateway:

```console
sudo python3 scripts/pricetag/providers pricetag --debug
```

Enter the upstream hostname once, review both printed credential destinations,
then paste its key at the hidden prompt. HTTPS and the OpenAI `/v1` suffix are
added automatically. Direct OpenAI keeps its separate key. The default path
requires successful model discovery; preset IDs not advertised by that catalog
are skipped. A credential-dependent catalog can omit working models. Absence
does not establish that inference is unavailable.

<details>
<summary>Authentication, incomplete catalogs and setup retries</summary>

For the paired route convention, the helper maps the leading
`ai-gateway-unified-` / `ai-gateway-openai-` hostname prefix; otherwise both APIs
use the same host. Supply both overrides when the API hosts are unrelated:

```console
sudo python3 scripts/pricetag/providers pricetag \
  --anthropic-url 'MESSAGES_HOST' --openai-url 'OPENAI_HOST' --debug
```

Use the prompt or the override command, not both. One PriceTag key must authorize
both APIs. Messages discovery uses `x-api-key` and `anthropic-version`;
OpenAI discovery uses `Authorization: Bearer`. Follow the instructions for your
credential. For a gateway whose catalog needs the same header on both API hosts,
add `--catalog-auth x-api-key` or `--catalog-auth bearer`. This changes **discovery
only**. Inference defaults to Messages `x-api-key` and OpenAI Bearer headers;
use `--messages-auth bearer` when your credential requires Bearer for Messages
discovery and inference. The Messages client supplies `anthropic-version`. Credentials never go in an
inference JSON body. A successful catalog request does not prove both inference
APIs accept that key.

Pin a reviewed model when the catalog omits it:

```console
sudo python3 scripts/pricetag/providers pricetag --debug \
  --pin-model anthropic:rits/zai-org/glm-5-3
```

Pins are restricted to `configs/pricetag/provider-models.json`; repeat the option
for other reviewed presets. They are marked unverified when not advertised and
do not bypass authentication failures. GLM uses **262,144 context / 65,536 maximum
output tokens**, and is **text-only**. The OpenCode launcher declares text-only
modalities and disables attachments. Start a fresh conversation without images;
images in history can still cause upstream HTTP 400. Test inference before
distributing access. Do not increase client limits beyond the documented caps.

If the initial `/v1/models` returns **404, 405 or 501**, first verify
the URL. For an endpoint known not to implement discovery, explicitly opt in:

```console
sudo python3 scripts/pricetag/providers pricetag --allow-unverified-models --debug
```

This warns and uses the reviewed presets for the affected API, recording it as
unverified. It does **not** validate that key, model entitlement or served limits.
Test real inference before distributing access. Authentication errors (401/403),
TLS failures, timeouts, rate limits and other server errors still stop setup.
An empty or malformed catalog is not treated as missing discovery.

Before activation, add `--replace` to replace saved inputs using a new key.
On a running gateway, OpenAI key replacement and PriceTag endpoint/key replacement are supported;
follow [provider maintenance](pricetag.md#replace-a-running-gateways-pricetag-endpoint-or-key).
Do not rerun `prepare` to update a running deployment.

The other Messages presets have conservative configured limits, not verified
upstream maxima. A pricing row does not create an inference route. Review exact upstream
IDs, native APIs, limits and prices before adding presets. Debug output omits
keys and response bodies but includes your entered endpoints; redact those
addresses before posting logs publicly.

</details>

### Export, prepare and start

Export all configured providers; OpenAI-only and PriceTag-only are supported:

```console
sudo python3 scripts/pricetag/providers export
```

Aliases remain `openai/MODEL` and `pricetag/MODEL`. Praxis selects the configured
native API/provider key and rewrites the alias to the upstream ID. Inspect the
exported `models.json`, `providers.json` and `prices.json` if needed; they contain
configuration and secret references, not key values.

Use the host saved during source transfer. For DNS, replace this value with
the exact name clients will use before running preparation:

```console
GATEWAY_HOST="$(cat ~/pricetag-gateway-host)"
PRICETAG_UID=$(id -u praxis-svc)
sudo install -m 0644 configs/common/quadlet/praxis.network \
  "/etc/containers/systemd/users/$PRICETAG_UID/praxis.network" &&
sudo python3 scripts/pricetag/prepare.py \
  --hostname "$GATEWAY_HOST" --praxis-image "$PRAXIS_IMAGE" \
  --metering-image "$METERING_IMAGE" \
  --providers /root/pricetag-provider-inputs/providers.json \
  --models /root/pricetag-provider-inputs/models.json \
  --provider-unit /root/pricetag-provider-inputs/provider-secrets.container \
  --price-sources /root/pricetag-provider-inputs/prices.json \
  --price-seeds configs/pricetag/price-seeds.json --monthly-usd 5
```

<details>
<summary>How the pricing catalog and supplemental seeds work</summary>

`configs/pricetag/price-seeds.json` supplies reviewed fallback USD-per-million
rates for selected models missing from the pinned catalog. Review these against
the provider's rates before launch; existing fetched prices are preserved.
Only selected source IDs are seeded. Missing unseeded prices stop startup rather
than silently choosing another model's rate. Flat rates do not cover every
upstream charge or long-context surcharge.

This file is supplemental, not the full pricing catalog:

| Model | Price source in the pinned metering build | Inference availability |
| --- | --- | --- |
| `gpt-5.4-mini` | Already present in the bundled catalog; no additional seed needed | The provider helper enables it only when upstream discovery advertises it |
| `gpt-6-luna`, `gpt-6.1-sol` | Additional fallback rows in `price-seeds.json` | Also require upstream discovery |
| `rits/zai-org/glm-5-3` | Metering already seeds all token rates at zero | Messages preset; enable when advertised or explicitly pin for an incomplete catalog, then test inference |

Gateway aliases such as `openai/gpt-5.4-mini` and `pricetag/gpt-5.4-mini`
receive copies of their selected source prices during bootstrap. A rate-card
entry does not make a model available through `/v1/models`.

</details>

Review `/etc/praxis-pricetag/quadlets`, `models.json` and `bootstrap.sql`, then:

```console
sudo scripts/pricetag/start
```

Do not rerun `prepare` after successful preparation. `start` can retry a failed
startup and preserves the existing database/issuer. It starts PostgreSQL,
metering and Praxis as rootless Quadlet/systemd services with boot persistence.
The gateway uses USD enforcement plus PriceTag's retained 10-billion-token
monthly safety net; the Praxis token-rate limiter is removed.

<details>
<summary>Alternative for the separate performance VM: install the mock provider</summary>

Run this section only on `pricetag-perf`. Its mock mode is independent of the
real-provider configuration and does not mount real provider secrets.
Choose this VM's public IP/DNS name:

```console
GATEWAY_HOST="$(cat ~/pricetag-gateway-host)"
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

</details>

## 5. Verify services and provision users — RHEL

Run after starting either deployment. Define `svc` in each new SSH session:

```console
PRICETAG_UID=$(id -u praxis-svc)
svc() {
  (cd /tmp && sudo -u praxis-svc env \
    XDG_RUNTIME_DIR="/run/user/$PRICETAG_UID" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$PRICETAG_UID/bus" "$@")
}
svc systemctl --user status pricetag-db.service pricetag-metering.service \
  pricetag-gateway.service --no-pager
loginctl show-user praxis-svc -p Linger
sudo curl --fail --cacert /etc/praxis-pricetag/ca.pem https://localhost:8443/login >/dev/null
```

Expect all three services `active (running)` and `Linger=yes`. For the performance
VM also check `svc systemctl --user status pricetag-provider --no-pager`.
Allow TCP 8443 in the public interface's zone if firewalld is active. The AWS
security group continues to restrict source IPs. Run on RHEL:

```console
if sudo systemctl is-active --quiet firewalld; then
  GATEWAY_IFACE=$(ip -o route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="dev") {print $(i+1); exit}}')
  GATEWAY_ZONE=$(sudo firewall-cmd --get-zone-of-interface="$GATEWAY_IFACE")
  if [ -z "$GATEWAY_ZONE" ] || [ "$GATEWAY_ZONE" = "no zone" ]; then
    GATEWAY_ZONE=$(sudo firewall-cmd --get-default-zone)
  fi
  sudo firewall-cmd --zone="$GATEWAY_ZONE" --add-port=8443/tcp &&
    sudo firewall-cmd --permanent --zone="$GATEWAY_ZONE" --add-port=8443/tcp
fi
```

PostgreSQL and metering ports remain private.

Provision the two initial users with independent $5 monthly allowances:

```console
cd ~/secure-single-server-pricetag
sudo python3 scripts/pricetag/user --subject alice --name Alice --rotate \
  --monthly-usd 5 --output /root/pricetag-admin/alice-ready.jwt &&
sudo python3 scripts/pricetag/user --subject bob --name Bob --rotate \
  --monthly-usd 5 --output /root/pricetag-admin/bob-ready.jwt &&
sudo python3 scripts/pricetag/credentials list
```

Expect `Credential saved` for each user. `credentials list` shows JWT status,
not proof of identity/budget setup. These commands link spending identities,
set overrides and rotate the initial JWTs. Do not delete an existing output
file to rerun a successful rotation; use a new filename for deliberate renewal.
See [user administration](pricetag.md#administrator-scripts-provision-rotate-and-revoke)
for adding users, changing budgets, rotation and revocation.

| Login | Current JWT path after the steps above |
| --- | --- |
| Admin | `/root/pricetag-admin/admin.jwt` |
| Alice | `/root/pricetag-admin/alice-ready.jwt` |
| Bob | `/root/pricetag-admin/bob-ready.jwt` |

Read only the token you need, on RHEL:

```console
sudo cat /root/pricetag-admin/admin.jwt
```

For a user login substitute their path from the table. Initial `alice.jwt` and
`bob.jwt` are now superseded. Signing keys stay on RHEL. JWTs have no automatic
expiry; browser sessions can survive JWT revocation until their seven-day expiry.

## 6. Connect your browser and OpenCode — workstation

Leave the RHEL shell open. In the original workstation terminal, select the
intended VM again. Restoring
an existing terminal/session is covered in [AWS operations](aws-operations.md).
This does not launch another instance:

```console
cd "$SERVER_CHECKOUT"
VM_NAME=pricetag-real
aws_test_verify "$VM_NAME"
CLIENT_DIR="$HOME/.config/praxis-pricetag/$RUN_PREFIX-$VM_NAME"
GATEWAY_URL="https://${RHEL_HOST#*@}:8443"
install -d -m 0700 "$CLIENT_DIR"
umask 077
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
  'sudo -n cat /etc/praxis-pricetag/ca.pem' > "$CLIENT_DIR/ca-next.pem" &&
  mv "$CLIENT_DIR/ca-next.pem" "$CLIENT_DIR/ca.pem"
```

If preparation used DNS, set `GATEWAY_URL` to that exact HTTPS hostname and port.
Copying the CA does not import it into browser trust. On macOS, open the CA in
Keychain Access and trust it for SSL, or accept a browser certificate exception
if your browser permits one. This exception does not configure CLI trust.

On macOS:

```console
open "$CLIENT_DIR/ca.pem"
open "$GATEWAY_URL/login"
```

Paste the admin JWT read on RHEL and visit `/admin#quotas` to inspect allowances.
Use a separate browser profile with Alice's JWT for `/dashboard`. Browser-only
use needs no local JWT file. No SSH tunnel is required.

For OpenCode, copy only Alice's JWT to a private local file:

```console
umask 077
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
  'sudo -n cat /root/pricetag-admin/alice-ready.jwt' > "$CLIENT_DIR/caller-next.jwt" &&
  mv "$CLIENT_DIR/caller-next.jwt" "$CLIENT_DIR/caller.jwt"
```

Choose a configured alias from the successful provider setup output. Preview:

```console
MODEL_ALIAS='openai/gpt-6-luna'
python3 "$SERVER_CHECKOUT/scripts/pricetag/harness" opencode --url "$GATEWAY_URL" \
  --token-file "$CLIENT_DIR/caller.jwt" --ca-file "$CLIENT_DIR/ca.pem" \
  --model "$MODEL_ALIAS" --print-config
```

If that model was skipped, use an enabled alias instead. With OpenCode installed,
change into your project directory and launch with the same settings:

```console
cd /absolute/path/to/your/project
python3 "$SERVER_CHECKOUT/scripts/pricetag/harness" opencode --url "$GATEWAY_URL" \
  --token-file "$CLIENT_DIR/caller.jwt" --ca-file "$CLIENT_DIR/ca.pem" \
  --model "$MODEL_ALIAS"
```

`--model` selects the starting model, not the whole menu. Run `/models` in
OpenCode to switch among all advertised aliases:

| OpenCode provider | Catalog entries | Wire API |
| --- | --- | --- |
| `praxis-openai` | Direct `openai/…` and upstream `pricetag/…` OpenAI models | Responses for GPT-5/GPT-6/o1/o3/o4; Chat for other OpenAI models |
| `praxis-messages` | Messages-capable `pricetag/…` aliases | Anthropic Messages |

<details>
<summary>What the per-session harness configuration changes</summary>

The launcher carries each model's context/output limits, enables only those
providers, filters inherited model entries and uses the starting model for
background tasks. Configuration is per process; your persistent OpenCode file
is unchanged. Relaunch to refresh the gateway catalog. Provider secrets remain
on RHEL; the client has only its caller JWT and public CA.

For on-VM testing use `https://localhost:8443` with the same CA and user JWT;
JWT authentication still applies. The performance VM uses `demo-model`; preview
only for harness configuration, since its fixture cannot do coding tasks.

</details>

## 7. Qualify the deployment and continue administration

A working catalog does not prove every upstream can complete requests. Test a
small inference and a real tool task on each intended model; check usage and
USD budgets in the dashboard. Also verify invalid-JWT denial, ordinary-user
admin denial, revocation and accounting after restart. Keep access IP-bound
until these pass.

For later user creation, JWT rotation/revocation and allowance changes, use
[user administration](pricetag.md#administrator-scripts-provision-rotate-and-revoke).
Those operations do not require first-time preparation again.

For the separate mock-only VM, follow [performance and storage measurements](pricetag-perf.md).
Use distinct test users and staged load; record request metrics together with
CPU/RAM, PostgreSQL/WAL, logs and disk growth. A workstation/Podman result is
not evidence of RHEL capacity. No automatic raw-usage retention is configured;
review the retention section before a long-running deployment.


## Open the real server to any IP later

After qualification, use [public HTTPS access and rollback](pricetag-access.md).
That optional procedure changes the real server's TCP 8443 ingress and reconciles
its launch journal; SSH and the performance VM remain restricted.
