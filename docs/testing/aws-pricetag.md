# Deploy the single-server MaaS and PriceTag pilot

This runbook deploys the real-provider gateway and a separate mock-only
performance gateway on RHEL. Each host runs Praxis, the standalone MaaS API,
PriceTag metering and PostgreSQL as rootless Quadlet services. Only Praxis
HTTPS on TCP 8443 is public. MaaS and PostgreSQL are private; MaaS also has a
loopback-only host port for administrator scripts.

The standalone MaaS runtime and the Praxis image with `api_key_auth` and
`external_metering` are prerequisites. Use reviewed immutable source/image
revisions. This deployment uses finite MaaS API keys and PriceTag USD budgets;
it does not configure Praxis `token_rate_limit`. The gateway-to-metering M2M
bearer credential is stored as a Podman secret; MaaS and PostgreSQL remain
private. Do not expose the MaaS port.

## 1. Launch the RHEL hosts

Run on an AWS administrator workstation from a reviewed checkout of
`redhat-et/secure-single-server`. The AWS helper creates encrypted root disks
and security groups restricted to the workstation's public IPv4 `/32`.
Choose the source checkout and AWS values for your environment:

```console
cd /absolute/path/to/secure-single-server
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

Review and launch the real-provider server:

```console
aws_test_plan pricetag-real "${PRICETAG_VM[@]}"
aws_test_deploy pricetag-real "${PRICETAG_VM[@]}"
PRICETAG_INSTANCE=$(jq -er '.InstanceId' \
  ".state/$RUN_PREFIX-pricetag-real.json")
aws --region "$REGION" ec2 wait instance-running --instance-ids "$PRICETAG_INSTANCE"
aws_test_verify pricetag-real
```

Launch a second VM for performance work. Never configure real upstream
credentials on this host:

```console
aws_test_plan pricetag-perf "${PRICETAG_VM[@]}"
aws_test_deploy pricetag-perf "${PRICETAG_VM[@]}"
PRICETAG_INSTANCE=$(jq -er '.InstanceId' \
  ".state/$RUN_PREFIX-pricetag-perf.json")
aws --region "$REGION" ec2 wait instance-running --instance-ids "$PRICETAG_INSTANCE"
aws_test_verify pricetag-perf
```

`aws_test_verify` prints the current SSH host, key path and journal for the
selected VM. If the instance is still pending, rerun the waiter and verify;
never rerun deploy for an instance that already exists. Keep both journals.
The 32-GiB, 150-GiB instance profile is a test starting point, not a capacity
claim. See [AWS operations](aws-operations.md) for restoring a launch session,
printing both VM details, and changing ingress.

## 2. Copy the reviewed server branch and connect

Repeat for each VM. On the workstation, select and verify the destination:

```console
VM_NAME=pricetag-real
aws_test_verify "$VM_NAME"
printf 'Destination: %s\n' "$RHEL_HOST"
```

Copy the tracked source from the reviewed branch, then connect:

```console
(
  set -o pipefail
  git ls-files -z | tar --no-xattrs --null -T - -czf - | \
    ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
      'mkdir -p ~/secure-single-server && tar -xzf - -C ~/secure-single-server'
)
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST"
```

For the second host, return to the workstation and set `VM_NAME=pricetag-perf`,
then repeat. This transfers tracked files from the current checkout, including
its working-tree edits. Review the staged diff before copying; do not include
credential files or `.state` data.

## 3. Prepare RHEL and build pinned images

Run on each RHEL host after copying the source:

```console
sudo dnf install -y podman git python3 python3-pyyaml openssl \
  policycoreutils-python-utils shadow-utils
cd ~/secure-single-server
sudo scripts/common/install --prepare
```

Build the MaaS API from the reviewed standalone-runtime commit and build
unmodified PriceTag metering from the revision pinned by this repository. The
MaaS checkout must include `maas-api/Dockerfile` and `maas-api/`:

```console
git clone https://github.com/Ladas/models-as-a-service.git ~/models-as-a-service
git -C ~/models-as-a-service checkout --detach REVIEWED_MAAS_COMMIT
sudo scripts/pricetag/build-maas --source ~/models-as-a-service \
  --expected-commit REVIEWED_MAAS_COMMIT
git clone https://github.com/redhat-et/pricetag-metering.git ~/pricetag-metering
sudo scripts/pricetag/build-metering --source ~/pricetag-metering
```

Build the combined Praxis image from the reviewed experimental revision. It
pins the reviewed `redhat-et/praxis-ai` source and includes this repository's
filters. `--format docker` preserves the health check declared by its
Containerfile.

```console
git clone https://github.com/praxis-proxy/experimental.git ~/praxis-experimental
git -C ~/praxis-experimental checkout --detach REVIEWED_EXPERIMENTAL_COMMIT
sudo podman build --pull=always --format docker \
  --label org.opencontainers.image.revision=REVIEWED_EXPERIMENTAL_COMMIT \
  --tag localhost/praxis-experimental:reviewed \
  --file ~/praxis-experimental/Containerfile ~/praxis-experimental
```

Record the full image ID; do not deploy from a floating tag.

Import all three local images into the rootless service account and capture
their immutable IDs. Set `PRAXIS_IMAGE` to the image built or pulled above:

```console
PRICETAG_UID=$(id -u praxis-svc)
svc() {
  (cd /tmp && sudo -u praxis-svc env \
    XDG_RUNTIME_DIR="/run/user/$PRICETAG_UID" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$PRICETAG_UID/bus" "$@")
}
PRAXIS_IMAGE=localhost/praxis-experimental:REVIEWED_TAG
podman save "$PRAXIS_IMAGE" | svc podman load
podman save localhost/pricetag-maas:standalone | svc podman load
podman save localhost/pricetag-metering:upstream-557ceb1 | svc podman load
PRAXIS_IMAGE=$(svc podman image inspect "$PRAXIS_IMAGE" --format '{{.Id}}')
MAAS_IMAGE=$(svc podman image inspect localhost/pricetag-maas:standalone --format '{{.Id}}')
METERING_IMAGE=$(svc podman image inspect localhost/pricetag-metering:upstream-557ceb1 --format '{{.Id}}')
```

Stop if any image ID is not `sha256:` followed by 64 lowercase hexadecimal
characters. Image build support does not publish or sign images.

## 4. Configure the real gateway providers

Run only on `pricetag-real`. The helper asks for credentials using hidden
prompts, performs HTTPS model discovery, and stores provider secrets separately
from the MaaS user keys. Choose one or both provider types:

```console
cd ~/secure-single-server
sudo python3 scripts/pricetag/providers openai
sudo python3 scripts/pricetag/providers pricetag
sudo python3 scripts/pricetag/providers export
```

For PriceTag, enter the Messages hostname once; the helper derives the paired
OpenAI hostname when applicable and adds HTTPS and `/v1`. Use the explicit
discovery options only when the provider documents a nonstandard catalog or
omits an entitled model. A model listed locally is not proof that the provider
will accept an inference request. Review the generated model IDs, API types,
limits and price mappings before preparing the host.

Skip this section on `pricetag-perf`; it uses only the synthetic provider.

## 5. Prepare and start the services

On the real host, export the provider configuration. Set `GATEWAY_HOST` to the
DNS name clients will use, or the VM public IP for the initial IP-bound test.
The TLS certificate includes that name and localhost.

```console
GATEWAY_HOST='gateway.example.invalid'
sudo python3 scripts/pricetag/prepare.py \
  --hostname "$GATEWAY_HOST" --praxis-image "$PRAXIS_IMAGE" \
  --maas-image "$MAAS_IMAGE" --metering-image "$METERING_IMAGE" \
  --providers /root/pricetag-provider-inputs/providers.json \
  --models /root/pricetag-provider-inputs/models.json \
  --provider-unit /root/pricetag-provider-inputs/provider-secrets.container \
  --price-sources /root/pricetag-provider-inputs/prices.json \
  --monthly-usd 5
sudo scripts/pricetag/start
```

On the performance host, use the same `GATEWAY_HOST` selection and run:

```console
GATEWAY_HOST='PERFORMANCE_VM_PUBLIC_IP_OR_DNS'
sudo python3 scripts/pricetag/prepare.py --mock-provider \
  --hostname "$GATEWAY_HOST" --praxis-image "$PRAXIS_IMAGE" \
  --maas-image "$MAAS_IMAGE" --metering-image "$METERING_IMAGE" \
  --price-sources configs/pricetag/perf-price-sources.json --monthly-usd 5
sudo scripts/pricetag/start
```

The performance price source must be a reviewed local fixture file mapping
`fixture` to a model already priced in the pinned metering image. Do not use
real provider secrets or aliases on this VM. `prepare.py` refuses to overwrite
existing deployment directories. `start` installs and starts user Quadlets;
PostgreSQL, MaaS, metering, the optional mock, and Praxis start on boot.

For an existing deployment, first make a root-only backup of its configuration,
Quadlet units, and PostgreSQL data. Stop the old services, then move
`/etc/praxis-pricetag` aside and prepare directly at that path with a new
`--admin-directory`. Preserve the existing `pricetag-data` volume and provider
Podman secrets. `start` detects the existing `metering`-superuser PostgreSQL
layout, creates the MaaS database, updates the application-role passwords, and
preserves existing metering rows. It also detects an existing
`pricetag-private` subnet and aligns the MaaS trusted-proxy CIDR with it; a new
network uses the subnet in the Quadlet definition. It refuses to apply the
initial USD policy and model aliases when `usage_events` is nonempty. After
reviewing the backup, schema, and configured price-source IDs, explicitly
adopt that database with:

```console
sudo scripts/pricetag/start --adopt-existing-database
```

This applies the reviewed USD policy and missing model aliases idempotently;
it does not delete usage history. The ordinary `start` command continues to
refuse first-time bootstrap on a nonempty database.

## 6. Check services and issue user keys

On each host, confirm that services are active and user lingering is enabled:

```console
PRICETAG_UID=$(id -u praxis-svc)
svc() {
  (cd /tmp && sudo -u praxis-svc env \
    XDG_RUNTIME_DIR="/run/user/$PRICETAG_UID" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$PRICETAG_UID/bus" "$@")
}
svc systemctl --user status pricetag-db.service pricetag-maas.service \
  pricetag-metering.service pricetag-gateway.service --no-pager
loginctl show-user praxis-svc -p Linger
sudo curl --fail --cacert /etc/praxis-pricetag/ca.pem \
  https://localhost:8443/login >/dev/null
```

On first start, the deployment creates an administrator key and Alice and Bob
keys, each with a $5 monthly override. Read only the key you need:

```console
sudo find /root/pricetag-admin -maxdepth 1 -type f -name '*.key' -print
sudo cat /root/pricetag-admin/admin.key
sudo cat /root/pricetag-admin/alice.key
```

Treat these as passwords. Copy keys through a protected channel and delete
temporary copies after installation. Create or rotate a user's named key with
`scripts/pricetag/user`; use a new output filename because the tool will not
overwrite a credential file:

```console
sudo python3 scripts/pricetag/user --subject alice --name Alice --rotate \
  --monthly-usd 5 --output /root/pricetag-admin/alice-next.key
```

The old key is revoked only after the replacement is saved. For direct key
operations, `scripts/pricetag/maas-key` provides create, list, rotate and revoke
through MaaS APIs. Set an explicit maximum key lifetime on the MaaS service;
this profile configures 90 days. PriceTag browser sessions have their own
expiry and are not MaaS API keys.

## 7. Open the dashboard and connect OpenCode

On the workstation, copy the public CA and a user's MaaS key into a private
directory. Replace the variables with the values printed by AWS verification:

```console
VM=ec2-user@PUBLIC_IP
SSH_KEY="$HOME/.secure-single-server-tests/ssh/$RUN_PREFIX"
CLIENT_DIR="$HOME/.config/praxis-pricetag/$RUN_PREFIX"
mkdir -m 700 -p "$CLIENT_DIR"
umask 077
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$VM" \
  'sudo cat /etc/praxis-pricetag/ca.pem' > "$CLIENT_DIR/ca.pem"
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$VM" \
  'sudo cat /root/pricetag-admin/alice.key' > "$CLIENT_DIR/alice.key"
chmod 600 "$CLIENT_DIR/ca.pem" "$CLIENT_DIR/alice.key"
```

Open `https://PUBLIC_IP:8443/login` in a browser, accept or install the
deployment CA, then sign in with the administrator key. Use a separate browser
profile and the user's key for the personal dashboard. Keep TCP 8443 restricted
to approved client IPs until authentication, accounting, quotas, and dashboard
authorization pass the acceptance checks.

Launch OpenCode for one project and one session:

```console
cd /path/to/your/project
python3 /path/to/secure-single-server/scripts/pricetag/harness opencode \
  --url https://PUBLIC_IP:8443 --key-file "$CLIENT_DIR/alice.key" \
  --ca-file "$CLIENT_DIR/ca.pem" --model openai/gpt-6-luna
```

Choose a model alias actually enabled in `models.json`; it is the initial
model for the session. The helper configures temporary OpenAI-compatible and
Anthropic providers with every model in the gateway catalog and its context
and output limits, so OpenCode's [model picker](https://docs.opencode.ai/docs/models/)
can switch among them. It does not edit persistent OpenCode configuration.

## 8. Run performance tests and review storage

Run the bounded test only on the mock performance server. See
[the performance procedure](pricetag-perf.md) for workload, exact ledger
reconciliation, resource sampling, database growth and cleanup. Do not mix
real-provider requests or real users into the performance report.

Raw usage-event retention is not configured by this deployment. Measure table,
WAL, log and disk growth during a soak, keep encrypted off-host backups, and set
an explicit retention policy before long-lived service. Per-user dashboard
isolation and recovery from an off-host backup remain acceptance gaps; a healthy
systemd status is not evidence that these features are qualified.
