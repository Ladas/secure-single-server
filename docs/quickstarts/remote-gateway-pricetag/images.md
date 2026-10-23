# Application images

The installer supports two image modes. Both use the same provider setup,
Quadlets and readiness checks. Praxis and PostgreSQL keep their existing pinned
published images.

| Mode | MaaS and PriceTag |
| --- | --- |
| `--image-mode source` | Build the pinned application revisions on RHEL. Current default; useful before publication and for testing new revisions. |
| `--image-mode published` | Pull two explicit `repository@sha256:digest` references. No application source checkout or Go build. |

The interactive installer offers this choice. Noninteractive commands default
to source builds unless image references are supplied. It verifies application
source labels and CPU architecture before preparing the deployment.

## Published images

Use the two digest references printed by a successful image-publication run.
The planned repositories are:

```text
quay.io/redhat-et/secure-single-server-maas-standalone
quay.io/redhat-et/secure-single-server-pricetag-metering
```

Until the first publication succeeds, use source mode. No `latest` tag or
placeholder digest is assumed. The initial publisher targets `linux/amd64`.

On a fresh RHEL host, after copying the checkout:

```console
cd ~/secure-single-server
read -r -p 'Gateway IP or DNS: ' GATEWAY_HOST
read -r -p 'MaaS repository@sha256:digest: ' MAAS_IMAGE
read -r -p 'PriceTag repository@sha256:digest: ' METERING_IMAGE
sudo scripts/pricetag/install --mode real --hostname "$GATEWAY_HOST" \
  --image-mode published --maas-image "$MAAS_IMAGE" --metering-image "$METERING_IMAGE"
```

Provider selection and hidden credential prompts follow. For unattended
configuration, combine these options with the [private credential-file
options](providers.md). Never put provider keys in command-line arguments.

## Test a new source revision

Use full 40-character Git commit SHAs reachable from the configured source
repositories: [MaaS fork](https://github.com/Ladas/models-as-a-service) and
[PriceTag metering](https://github.com/redhat-et/pricetag-metering).

```console
cd ~/secure-single-server
read -r -p 'Gateway IP or DNS: ' GATEWAY_HOST
read -r -p 'MaaS source commit: ' MAAS_REVISION
read -r -p 'PriceTag source commit: ' METERING_REVISION
sudo scripts/pricetag/install --mode real --hostname "$GATEWAY_HOST" \
  --image-mode source --maas-revision "$MAAS_REVISION" --metering-revision "$METERING_REVISION"
```

Omit either revision option to keep its qualified default. The MaaS checkout
must provide the standalone runtime; arbitrary upstream versions may not work.
New PriceTag revisions may change schemas, authentication or dashboard routes;
a successful build does not establish gateway compatibility.

The same revision options specify expected source labels when pulling newly
published images. A mismatch stops installation. Labels document provenance;
they are not cryptographic signatures. Use digests from a trusted publisher.

These are **fresh installation** options. Existing deployments are refused;
this command does not perform upgrades or database migrations for an existing
gateway.
