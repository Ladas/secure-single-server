# RHEL 9 bootc images

bootc turns the reviewed Praxis/OpenShell setup into a repeatable host deployment.
Choose a harness image, provision credentials separately, then update or roll back
the OS as an image. OpenShell supplies the sandbox; Praxis supplies model access
and shared quotas. Their combined inference path remains
[experimental](../docs/quickstarts/openshell-praxis/users.md).

Build one x86_64 bootable base and three derived OS images:

```text
RHEL 9 bootc → secure-single-server:base
              ├── :codex
              ├── :opencode
              └── :openclaw
```

The base includes Podman, the native OpenShell CLI, deployment configuration,
and a boot service for Praxis and OpenShell. Each child adds one harness's
selection and scripts/policies. Harness binaries run in the pinned workload
containers, not directly on the host. This initial bootc path uses Praxis's
in-memory quota profile and administrator-operated OpenShell. It does not yet
provide Valkey, remote-gateway TLS/JWT, or ordinary-user access to OpenShell.
It is a deployment foundation for the [phased gateway goals](../docs/roadmap.md),
not completion of the durable-quota or retained-session requirements.

## Pull on first boot

Application containers are **not embedded** in the OS image. First boot pulls
the repository's digest-pinned Praxis and OpenShell control-plane images,
plus only the selected harness image. This keeps OS distribution smaller;
the installed host still needs disk space for the OS, container cache and
workspace data. The native OpenShell CLI is copied from its pinned image at
build time so boot never writes into `/usr`.

Pulls use persistent, separate rootless stores for `praxis-svc` and
`openshell-svc`. Each boot checks for the exact pinned images locally before
pulling. A cached reboot needs no registry access. A new OS deployment with
new pins needs registry access again. Failed pulls leave the boot service
failed/retrying every 30 seconds, rather than starting with different tags.
The OS remains accessible for diagnosis. No automatic image pruning runs:
retain previous digests if you want offline rollback.

Initial startup requires DNS and HTTPS access to Quay and its blob storage
endpoints. The build also requires authenticated access to `registry.redhat.io`
and RHEL package repositories. Private workload registries need authentication
in the relevant service account's Podman authfile; credentials are never baked
into the image. Bootc's own OS-update registry credentials are separate.

## Build on a RHEL AWS builder

Use a dedicated x86_64 RHEL 9 instance. The repository's
[AWS helper](../docs/testing/aws.md) can provision it: select just one
`all-in-one` instance and allow SSH from your workstation's `/32`. A 100 GiB
encrypted root disk leaves room for builds and test artifacts. Run the
following **on the Linux builder**, not in macOS's local shell:

```console
sudo dnf install -y podman skopeo
sudo podman login registry.redhat.io
sudo skopeo inspect --format '{{.Digest}}' docker://registry.redhat.io/rhel9/rhel-bootc:9.8
```

Review and record the returned digest, then build from a transferred checkout:

```console
export RHEL_BOOTC_IMAGE=registry.redhat.io/rhel9/rhel-bootc@sha256:REVIEWED_DIGEST
sudo env RHEL_BOOTC_IMAGE="$RHEL_BOOTC_IMAGE" AWS_RHUI_REGION=us-east-1 bootc/build all
sudo bootc/test-images
```

`bootc/build` requires an immutable RHEL 9 reference and refuses non-amd64
builders. It constructs a restricted build context from deployment sources;
Git history, local evidence, AWS state and workstation credentials are excluded.
The harness builds resolve the base tag to its local image ID before deriving
the three images. Every image runs `bootc container lint` during its build.
Use a second argument such as `quay.io/YOUR_NAMESPACE/secure-single-server`
to select the output image prefix. Publishing is a separate `podman push` step.

Set `AWS_RHUI_REGION` to the builder's actual AWS region. On a PAYG RHEL host,
the helper temporarily mounts the host's RHUI repository definition, TLS
material, and AWS DNF plugin for package installation. Host networking lets
the plugin authenticate through IMDSv2 without changing the instance's metadata
hop limit; SELinux container labeling is disabled only for that build. Those
mounts are excluded from the resulting layers.
On a subscription-registered non-AWS builder, omit this variable and use
Podman's normal entitlement integration. Cloud-init is included for AWS
first-boot SSH-key provisioning.

## Install and boot

These are OS containers; `podman run` only tests their userspace. Use
[Red Hat's bootc image builder instructions](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/using_image_mode_for_rhel_to_build_deploy_and_manage_operating_systems/creating-bootc-compatible-base-disk-images-with-bootc-image-builder_using-image-mode-for-rhel-to-build-deploy-and-manage-operating-systems)
to create a disk image for the selected variant. Provision an administrator
SSH key in the disk-image configuration. For EC2, follow the documented AMI
workflow and supply the required AWS boot/network configuration; the build
host's existing RHEL AMI is not itself a test of bootc.

On a booted host:

```console
sudo journalctl -u secure-single-server.service -b
sudo sss-bootc openshell --version
sudo sss-bootc openshell sandbox list
```

The service creates locked, separate rootless accounts and enables lingering.
OpenShell listens on loopback ports 8090/8091 and gets only its own Podman
socket. It generates per-machine signing keys under `/var/lib/openshell`.
The OpenShell gateway retains the existing demo's SELinux-label-disable setting;
the host itself must keep SELinux enforcing. This is an administrator-trusted
demo boundary, not multi-tenant isolation.

## Provision Praxis secrets

Wait for the initial boot service to finish. It reports that Praxis awaits
secrets; OpenShell can already be inspected. Provider keys go through stdin to
the Praxis account's Podman secret store. Example in Bash, with tracing off:

```bash
set +x
read -r -s -p 'OpenAI key: ' key; printf '\n'
printf '%s' "$key" | sudo sss-bootc secret openai v1
unset key
read -r -s -p 'Anthropic key: ' key; printf '\n'
printf '%s' "$key" | sudo sss-bootc secret anthropic v1
unset key
sudo sss-bootc activate praxis-openai-api-key-v1 praxis-anthropic-api-key-v1
sudo sss-bootc status
```

Both names are required by the shipped two-provider Praxis configuration. For
no-provider smoke tests use explicit dummy values; this verifies service health,
not inference. Rotation uses new secret versions and another `activate` call.
Only names are stored in `/etc/secure-single-server/secret-names`.

The boot reconciler owns its generated Quadlets and Praxis memory configuration.
Change their sources and rebuild the OS, rather than running the mutable-host
installer/upgrade/uninstall commands on this deployment. Each boot re-renders
the units from that deployment's pins, which also applies after bootc rollback.
Keys, caches, workspaces and DB contents persist; OS rollback does not roll back
application data or guarantee compatibility with older database schemas.

After publishing a reviewed OS image, stage it with `sudo bootc switch
REGISTRY/IMAGE:RELEASE`, inspect `sudo bootc status`, then reboot. To return to
the previous OS deployment, use `sudo bootc rollback` and reboot. The selected
harness is part of the OS image, so switching from Codex to OpenCode uses the
same process. Local testing can use `bootc switch --transport containers-storage
localhost/secure-single-server:opencode` after loading that image into root's
Podman store; this does not exercise registry authentication or distribution.

## Use the selected harness

```console
sudo sss-bootc harness create --profile dev --name demo-dev
sudo sss-bootc harness connect --name demo-dev
```

These commands run the existing harness scripts as `openshell-svc`. Their
standalone policies permit provider endpoints. The
[Praxis integration workflow](../docs/quickstarts/openshell-praxis/README.md)
is separate and experimental. Codex and OpenClaw reject `--config`; OpenCode
renders a provider config but host-alias routing and real inference remain
unqualified. The pinned AWS sandbox did not resolve `host.openshell.internal`.
No SSH helper forwards provider keys. Standalone bindings must be explicit with
`--provider NAME`; integrated mode rejects them. Successful boot/build checks do
not prove a real model task works or that direct provider access is denied.

Start with `dev` for the CLI smoke test. OpenCode currently attempts to write
runtime state under `/sandbox/.local/share`, which the shipped read-only
`review` profile denies; sandbox creation can succeed while the CLI fails.
That profile needs a separate runtime-state policy design before it is usable
with OpenCode. Do not broaden the whole review workspace to work around it.

## Validation

See the [dated build and AWS boot results](VALIDATION.md) for tested image IDs,
checks and remaining qualification.

```console
python3 bootc/tests/build.py
shellcheck -x bootc/build bootc/test-images bootc/test-host bootc/scripts/*
sudo bootc/test-images
# On the booted host, after provisioning dummy or real secrets:
sudo bootc/test-host codex
```

The Python tests exercise build validation, parent-image selection and context
isolation. Container checks verify OS, CLI compatibility, service enablement,
absence of machine keys/secrets, and exactly one harness per child.
Host checks verify bootc, read-only `/usr`, SELinux, service health, rootless
account permissions, cached harness selection and loopback-only listeners.

Full acceptance also requires booting a disk/AMI with SELinux enforcing,
checking first-boot pulls and retry after registry failure, activating Praxis
with dummy secrets, rebooting with cached images, and exercising an OS update
and rollback. Real-provider harness and network-policy acceptance remain
separate. Record the OS and workload digests with each result.
