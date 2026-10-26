# Manual installation

Use these steps **instead of** the installer, on a fresh RHEL host after
[copying the checkout](README.md#2-copy-and-install). Run all blocks in the same
SSH session. From the workstation installation shell, connect first.
Stop at any failed command.

```console
ssh -t "${SSH_OPTS[@]}" "$RHEL_HOST" \
  'cd ~/secure-single-server && exec bash'
```

## 1. Prepare RHEL and images

Run on each RHEL host after copying the source:

```console
sudo dnf install -y podman git python3 python3-pyyaml openssl curl sudo \
  policycoreutils-python-utils shadow-utils
cd ~/secure-single-server
sudo scripts/common/install --prepare
```

Build the MaaS API from the reviewed standalone-runtime commit and build
unmodified PriceTag metering from the revision pinned by this repository. The
MaaS checkout must include `maas-api/Dockerfile` and `maas-api/`.
The minimal runtime branch includes the prerequisite
[standalone API-key PR #1548](https://github.com/opendatahub-io/models-as-a-service/pull/1548)
plus the runtime adaptation for operation without Kubernetes.
The commands pin the [reviewed runtime commit](https://github.com/Ladas/models-as-a-service/commit/6ac4c80ebc95f590e5f24593ac15bb80c7f9fa1d); they do not build from a moving branch tip:

```console
git clone --branch feat/standalone-runtime-minimal \
  https://github.com/Ladas/models-as-a-service.git ~/models-as-a-service
git -C ~/models-as-a-service checkout --detach 6ac4c80ebc95f590e5f24593ac15bb80c7f9fa1d
sudo scripts/pricetag/build-maas --source ~/models-as-a-service \
  --expected-commit 6ac4c80ebc95f590e5f24593ac15bb80c7f9fa1d
git clone https://github.com/redhat-et/pricetag-metering.git ~/pricetag-metering
sudo scripts/pricetag/build-metering --source ~/pricetag-metering
```

Pull the published combined Praxis image. This multi-architecture digest
contains the reviewed `redhat-et/praxis-ai` integration and experimental
filters from source revision `5667c4acecd0981ae5114cbbf2ee3dcccec9c248`.
This manual path builds MaaS and metering locally. The installer also supports
[pulling published application images by digest](images.md).

```console
PRAXIS_IMAGE=quay.io/opendatahub/praxis-experimental@sha256:502f120fed7b8e516ce1d78396045c8f72673672351432b9dc2e61baf5c13ac8
sudo podman pull "$PRAXIS_IMAGE"
sudo podman image inspect "$PRAXIS_IMAGE" \
  --format '{{index .Labels "org.opencontainers.image.revision"}}'
```

The revision must match the source above. See the
[publication and smoke-test workflow](https://github.com/opendatahub-io/praxis-experimental/actions/runs/39430750786).

Import all three local images into the rootless service account and capture
their immutable IDs. Set `PRAXIS_IMAGE` to the image built or pulled above:

```console
set -o pipefail
PRICETAG_UID=$(id -u praxis-svc)
svc() {
  (cd /tmp && sudo -u praxis-svc env \
    XDG_RUNTIME_DIR="/run/user/$PRICETAG_UID" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$PRICETAG_UID/bus" "$@")
}
PRAXIS_IMAGE=quay.io/opendatahub/praxis-experimental@sha256:502f120fed7b8e516ce1d78396045c8f72673672351432b9dc2e61baf5c13ac8
PRAXIS_ID=$(sudo podman image inspect "$PRAXIS_IMAGE" --format '{{.Id}}')
sudo podman save "$PRAXIS_IMAGE" | svc podman load
sudo podman save localhost/pricetag-maas:standalone | svc podman load
sudo podman save localhost/pricetag-metering:upstream-a33b90a | svc podman load
PRAXIS_IMAGE=$(svc podman image inspect "$PRAXIS_ID" --format '{{.Id}}')
MAAS_IMAGE=$(svc podman image inspect localhost/pricetag-maas:standalone --format '{{.Id}}')
METERING_IMAGE=$(svc podman image inspect localhost/pricetag-metering:upstream-a33b90a --format '{{.Id}}')
PRAXIS_IMAGE="sha256:${PRAXIS_IMAGE#sha256:}"
MAAS_IMAGE="sha256:${MAAS_IMAGE#sha256:}"
METERING_IMAGE="sha256:${METERING_IMAGE#sha256:}"
```

Stop if any image ID is not `sha256:` followed by 64 lowercase hexadecimal
characters. Image build support does not publish or sign images.

## 2. Configure providers

Run on the real-provider host. The helper asks for credentials using hidden
prompts, performs HTTPS model discovery, and stores provider secrets separately
from the MaaS user keys. Choose one or both provider types:

```console
cd ~/secure-single-server
sudo python3 scripts/pricetag/providers openai
sudo python3 scripts/pricetag/providers external --api both
sudo python3 scripts/pricetag/providers export
```

For the external provider, use `--api openai`, `--api anthropic`, or `--api both`.
Enter only the selected API endpoint(s), then the credential. HTTPS and `/v1`
normalization are automatic. At least one provider and a matching model preset
are required. Review the printed aliases, limits and price mappings.

See [provider setup and replacement](providers.md) for separate API
endpoints, discovery diagnostics, protected-file automation and replacement.


## 3. Start services

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
  --monthly-usd 5 --no-sample-users
sudo scripts/pricetag/start
```

This creates the administrator only. [Create an inference user](users.md#create-a-user)
next, or omit `--no-sample-users` during preparation to create Alice and Bob.

`prepare.py` refuses to overwrite
existing deployment directories. `start` installs and starts user Quadlets;
PostgreSQL, MaaS, metering, the optional mock, and Praxis start on boot. It
selects unused static addresses for MaaS, Praxis and PriceTag on
`pricetag-private`. MaaS trusts host loopback and only those three `/32`
service addresses; unrelated containers on the network are excluded.

This is a fresh-install procedure. Do not rerun preparation over an existing
installation or adopt an old database using these steps. Upgrades and recovery
need a separately qualified procedure.

## 4. Verify services

```console
svc systemctl --user status pricetag-db.service pricetag-maas.service \
  pricetag-metering.service pricetag-gateway.service --no-pager
loginctl show-user praxis-svc -p Linger
sudo curl --fail --cacert /etc/praxis-pricetag/ca.pem https://localhost:8443/login >/dev/null
```

Return to [dashboard and client setup](README.md#3-open-the-dashboards).
