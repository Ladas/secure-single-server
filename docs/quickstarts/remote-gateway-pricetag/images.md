# Application images

The installer supports two image modes. Both use the same provider setup,
Quadlets and readiness checks. Praxis and PostgreSQL keep their existing pinned
published images.

| Mode | MaaS and PriceTag |
| --- | --- |
| `--image-mode published` (default) | Pull the qualified MaaS and PriceTag images by digest. No application source checkout or Go build. |
| `--image-mode source` | Build from a branch or commit on RHEL to test a new version. |

The interactive installer recommends published images. Noninteractive commands
also default to published images. It verifies application
source labels and CPU architecture before preparing the deployment.

## Open the installation session

These are alternatives to the default installer command on a **fresh** host.
From the workstation shell used to copy the checkout:

```console
ssh -t "${SSH_OPTS[@]}" "$RHEL_HOST" \
  'cd ~/secure-single-server && exec bash'
```

Run the examples below in that SSH session. In a new workstation shell, restore
[connection settings](README.md#1-set-the-connection) first. Existing deployments
are refused; these options do not upgrade a running gateway.

## Published images

The installer pins both images from the [qualified publication run](https://github.com/redhat-et/secure-single-server/actions/runs/40324136393).
No image arguments are needed for the default installation. The repositories are:

```text
quay.io/redhat-et/secure-single-server-maas-standalone
quay.io/redhat-et/secure-single-server-pricetag-metering
```

The published images target `linux/amd64`. They are pinned in
`scripts/pricetag/install.py`; no moving `latest` tag is used. Override them only
to test another publication.

To override the default images on a fresh RHEL host, after copying the checkout:

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

## Build from a branch or commit

Source mode defaults to `feat/standalone-runtime-minimal` in the MaaS fork.
PriceTag keeps commit `a33b90ad1aea66479dbff99444ca819498589982` by default;
we do not maintain a modified PriceTag branch. Other revisions require
compatibility testing and are not selected automatically.

```console
cd ~/secure-single-server
read -r -p 'Gateway IP or DNS: ' GATEWAY_HOST
sudo scripts/pricetag/install --mode real --hostname "$GATEWAY_HOST" --image-mode source
```

To test other branches, add `--maas-branch BRANCH` and/or
`--metering-branch BRANCH`. Branches are fetched from the repositories below,
resolved to full commit SHAs, and printed before building. The fetched commit
is used even if the source cache contains an older local branch.

For reproducible source selection, use full 40-character Git commit SHAs
reachable from the configured source
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

A branch and a revision cannot be specified together for the same component.
Omit both MaaS selectors to use the fork branch; omit both PriceTag selectors
to keep its qualified commit. The MaaS checkout
must provide the standalone runtime; arbitrary upstream versions may not work.
New PriceTag revisions may change schemas, authentication or dashboard routes;
a successful build does not establish gateway compatibility.

The same revision options specify expected source labels when pulling newly
published images. A mismatch stops installation. Labels document provenance;
they are not cryptographic signatures. Use digests from a trusted publisher.

These are **fresh installation** options. Existing deployments are refused;
this command does not perform upgrades or database migrations for an existing
gateway.
