# Application images

Published images are the default. Source builds are for testing new versions.
Praxis and PostgreSQL remain pinned published images in either mode.

| Mode | MaaS and PriceTag |
| --- | --- |
| `--image-mode published` (default) | Pull the qualified MaaS and PriceTag images by digest. No application source checkout or Go build. |
| `--image-mode source` | Build from a branch or commit on RHEL to test a new version. |

The installer checks image source labels and CPU architecture.

## Open the installation session

For a **fresh host**, run from the workstation installation shell:

```console
ssh -t "${SSH_OPTS[@]}" "$RHEL_HOST" \
  'cd ~/secure-single-server && exec bash'
```

Run examples below in **this SSH session**. New shell? Restore
[connection settings](README.md#1-set-the-connection) first.

## Published images

Default repositories ([qualified publication](https://github.com/redhat-et/secure-single-server/actions/runs/40324136393)):

```text
quay.io/redhat-et/secure-single-server-maas-standalone
quay.io/redhat-et/secure-single-server-pricetag-metering
```

The published images target `linux/amd64`. They are pinned in
`scripts/pricetag/install.py`; no moving `latest` tag is used. Override them only
to test another publication.

<details>
<summary>Override published MaaS and PriceTag images</summary>

```console
cd ~/secure-single-server
read -r -p 'Gateway IP or DNS: ' GATEWAY_HOST
read -r -p 'MaaS repository@sha256:digest: ' MAAS_IMAGE
read -r -p 'PriceTag repository@sha256:digest: ' METERING_IMAGE
sudo scripts/pricetag/install --hostname "$GATEWAY_HOST" \
  --image-mode published --maas-image "$MAAS_IMAGE" --metering-image "$METERING_IMAGE"
```

Provider selection and hidden credential prompts follow. For unattended
configuration, combine these options with the [private credential-file
options](providers.md). Never put provider keys in command-line arguments.

</details>

<details>
<summary>Build from the default source revisions</summary>

Source mode defaults to `feat/standalone-runtime-minimal` in the MaaS fork.
PriceTag keeps commit `a33b90ad1aea66479dbff99444ca819498589982` by default;
we do not maintain a modified PriceTag branch. Other revisions require
compatibility testing and are not selected automatically.

```console
cd ~/secure-single-server
read -r -p 'Gateway IP or DNS: ' GATEWAY_HOST
sudo scripts/pricetag/install --hostname "$GATEWAY_HOST" --image-mode source
```

</details>

<details>
<summary>Build another branch or commit</summary>

For branches, add `--maas-branch BRANCH` and/or `--metering-branch BRANCH`
to source mode. For pinned commits, use the block below. Sources: [MaaS fork](https://github.com/Ladas/models-as-a-service) and
[PriceTag metering](https://github.com/redhat-et/pricetag-metering).

```console
cd ~/secure-single-server
read -r -p 'Gateway IP or DNS: ' GATEWAY_HOST
read -r -p 'MaaS source commit: ' MAAS_REVISION
read -r -p 'PriceTag source commit: ' METERING_REVISION
sudo scripts/pricetag/install --hostname "$GATEWAY_HOST" \
  --image-mode source --maas-revision "$MAAS_REVISION" --metering-revision "$METERING_REVISION"
```

Use a branch **or** a full SHA per component, never both. Branches resolve to a
printed commit before building. MaaS must include the standalone runtime;
PriceTag schema/API changes need compatibility testing.

</details>

<details>
<summary>Image verification and upgrade limits</summary>

Revision options also set expected source labels for published images. A mismatch
stops installation. Labels are provenance metadata, not signatures; use trusted
digests. These commands install fresh hosts, not upgrades or database migrations.

</details>
