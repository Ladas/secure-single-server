# Single-server bootc deployment

Use this route for a bootc OS image. For individual container installation,
use the [manual guide](manual.md). Review the [qualification and policy limits](reference.md).
For a short OpenCode/OpenAI walkthrough, use the [bootc quickstart](../bootc/README.md).


The quick path uses the project's published RHEL bootc image. Select exactly one
harness variant:

```text
quay.io/redhat-et/secure-single-server-opencode:v0.1
quay.io/redhat-et/secure-single-server-openclaw:v0.1
```

This demonstration intentionally uses the mutable `v0.1` tags directly. The
image contains the optional Praxis service, but it does not become a model
route until its separate secrets and activation workflow are configured; the
OpenShell sandbox checks do not depend on that service.

### Apply the image to an existing bootc host

On a booted RHEL image-mode host, deploy the selected image and reboot:

```console
sudo bootc switch quay.io/redhat-et/secure-single-server-opencode:v0.1
sudo bootc status
sudo systemctl reboot
```

Use the OpenClaw image reference instead when that is the selected harness.
Switching variants replaces the selected harness configuration; it does not
migrate existing sandboxes. Export and recreate them as needed.

### Apply the image to a fresh single server or bare-metal host

For a fresh VM or bare-metal host, use a standard bootc deployment workflow
and supply the selected published image as the source. Do not create or
substitute an unreviewed image. First boot pulls the pinned control-plane
and selected harness images.

For unreleased changes, build the images from the reviewed revision using the
[bootc build guide](../../../bootc/README.md), then install that exact image on a
disposable host. Published `v0.1` tags do not automatically include changes in
a pull request. Record the source revision and installed image digest during
qualification.

### Experiment with the container image in Podman

A bootc image is also a standard OCI container image. For lightweight
userspace experimentation, pull the published tag and start an interactive
shell with Podman. Replace the OpenCode reference with the OpenClaw variant
when needed:

```bash
podman pull quay.io/redhat-et/secure-single-server-opencode:v0.1
podman run --rm -it quay.io/redhat-et/secure-single-server-opencode:v0.1 bash
```

This does not boot the OS or run the boot reconciliation service, so it cannot
validate the always-on OpenShell gateway, lingering service account, host
SELinux state, or sandbox lifecycle. Use the VM or bare-metal deployment for
those qualification checks.

### Verify and create the sandbox

After boot, SSH to the administrator account and verify the deployment:

```console
sudo journalctl -u secure-single-server.service -b
sudo systemctl status secure-single-server.service --no-pager
sudo sss-bootc openshell --version
sudo sss-bootc openshell sandbox list
```

OpenShell is ready even if optional Praxis is waiting for secrets. For model
access, choose [OpenAI](#openai-api-key), an [existing local API](#local-openai-compatible-endpoint-and-key),
or the [bundled Praxis routes](#praxis-cloud-secrets-or-private-vllm) below.
The following sandbox without a provider is sufficient for shell and policy checks:

Create and connect the sandbox with the selected policy:

```console
sudo sss-bootc harness create --profile dev --name opencode-dev
sudo sss-bootc harness connect --name opencode-dev
```

For the OpenClaw image, use `openclaw-dev` as the name. OpenCode launches its
CLI; OpenClaw opens a shell because its browser service command is not yet
qualified.

The bootc service uses locked, separate rootless accounts and enables lingering.
OpenShell listens only on loopback ports 8090/8091. Keep SELinux Enforcing and
do not expose the management port beyond the host.
Reach the host remotely through your normal administrator SSH path, for example
`ssh -t ADMIN_USER@RHEL_HOST`, and then run `sudo sss-bootc harness connect`.
Do not publish OpenShell's management port to make remote access work.

## Configure model access

### OpenAI API key

The following example uses OpenCode. Run in Bash on the server after OpenShell
is ready. Create and review this non-secret profile; a fresh gateway has no
pre-imported provider profiles:

```bash
cat > /var/tmp/openai-model.yaml <<'YAML'
id: openai-model
display_name: OpenAI model access
category: inference
credentials:
  - name: api_key
    env_vars: [OPENAI_API_KEY]
    required: true
    auth_style: bearer
    header_name: authorization
endpoints:
  - {host: api.openai.com, port: 443, protocol: rest, access: read-write, enforcement: enforce}
binaries: [/usr/local/bin/opencode, /usr/bin/node-26]
YAML
sudo sss-bootc openshell profile lint -f /var/tmp/openai-model.yaml
sudo sss-bootc openshell profile import -f /var/tmp/openai-model.yaml
```

Register your actual OpenAI API key at the hidden prompt. The key is read inside
the service-account process, so it survives the administrator-to-service-account
boundary without appearing in command arguments:

```bash
uid="$(id -u openshell-svc)"
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus bash -c '
cd /
set -eu
set +x
IFS= read -r -s -p "OpenAI API key: " OPENAI_API_KEY; printf "\n"
export OPENAI_API_KEY
/usr/bin/openshell provider create --name openai-key --type openai-model \
  --credential OPENAI_API_KEY
unset OPENAI_API_KEY
'
```

Attach the provider when creating a new sandbox, then connect:

```bash
sudo sss-bootc harness create --profile dev --name opencode-openai --provider openai-key
sudo sss-bootc harness connect --name opencode-openai
```

In OpenCode, use `/models` to select an OpenAI model available to your account.
The attached provider supplies an opaque `OPENAI_API_KEY` placeholder; OpenShell
substitutes the real key only for the profile's authorized endpoint. Do not paste
the real key into OpenCode's `/connect` prompt or store it in harness config.
Follow the [model verification steps](verification.md#1-prove-model-interaction).
Verify model access on your host. The
[real-model deployment qualification](../../testing/upgrade-0.1.3-e2e.md) is
historical 0.1.3 evidence and does not replace a current-host check.

### Local OpenAI-compatible endpoint and key

For an existing authenticated local endpoint, use the same import, hidden-prompt,
and sandbox creation flow above with these substitutions:

| Setting | Local endpoint example |
| --- | --- |
| Profile file and `id` | `/var/tmp/local-model.yaml`, `local-model` |
| Profile endpoint | `host: inference.internal`, `port: 443` |
| Provider creation | `--name local-key --type local-model --credential OPENAI_API_KEY` |
| Prompt value | The key issued by your local inference server, not an OpenAI cloud key |
| Sandbox | `--name opencode-local --provider local-key` |
| Client base URL | `https://inference.internal/v1` |
| Model | The exact model ID served by that endpoint |

See the [complete local profile and OpenCode configuration](model-access.md#local-openai-compatible-service)
for copyable examples. Use the endpoint's actual host and port in both the
profile and client configuration. Changing only the base URL does not authorize
credential delivery to a new host. For inference on the OpenShell host, use
`host.openshell.internal`, rather than sandbox `localhost`.

A server that enforces bearer authentication needs its real key. A server that
does not authenticate requests needs a credentialless profile; an SDK may still
require a non-empty placeholder such as `unused`. The placeholder does not grant
access to an authenticated server.

### Praxis cloud secrets or private vLLM

Praxis stores provider keys separately from OpenShell provider attachments.
For cloud routing, enter the keys through stdin into versioned Podman secrets:

```bash
(
  set +x
  set -euo pipefail
  sudo -v
  IFS= read -r -s -p 'OpenAI API key: ' key; printf '\n'
  printf '%s' "$key" | sudo sss-bootc secret openai v1
  unset key
  IFS= read -r -s -p 'Anthropic API key: ' key; printf '\n'
  printf '%s' "$key" | sudo sss-bootc secret anthropic v1
  unset key
  sudo sss-bootc activate praxis-openai-api-key-v1 praxis-anthropic-api-key-v1
)
sudo sss-bootc inference cloud
```

The default cloud profile requires both secret names. For OpenAI-only use, the
direct provider recipe above avoids the two-provider Praxis setup. For a cloud
Praxis sandbox on the OpenCode image, choose an exact model ID your OpenAI
account can access. Configure the sandbox using the checkout included in the image:

```bash
IFS= read -r -p 'Approved OpenAI model ID: ' model_id
uid="$(id -u openshell-svc)"
cd /
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  OPENSHELL_BIN=/usr/bin/openshell OPENSHELL_MODEL_ID="$model_id" \
  /usr/share/secure-single-server/openshell/harnesses/opencode/create.sh \
  --profile dev --name opencode-praxis \
  --config /usr/share/secure-single-server/configs/openshell-praxis
sudo sss-bootc harness connect --name opencode-praxis
```

Do not attach `--provider` in this mode. The sandbox uses a placeholder key;
Praxis injects the stored OpenAI key upstream. See the
[integration limits](../openshell-praxis/users.md) and
[secret rotation](../../../bootc/README.md#optional-praxis-secrets).

For the project's separate private vLLM server, no OpenAI or upstream bearer key
is required by the bundled profile. After [deploying vLLM](../../../bootc/VLLM.md),
select its reachable private address on the OpenCode bootc host:

```bash
sudo sss-bootc inference remote-vllm 10.0.1.10:8000
sudo sss-bootc inference status
sudo sss-bootc inference check
sudo sss-bootc harness create --profile dev --name qwen-dev
sudo sss-bootc harness connect --name qwen-dev
```

Replace the example address with your inference server's address. The wrapper
configures `Qwen/Qwen3-8B` through Praxis automatically. Its `local-placeholder`
client key is not an upstream credential. This bundled route does not inject a
key into an authenticated vLLM upstream; use the authenticated local-provider
recipe above for an existing server that requires one. Rebuilt OpenClaw images
support the [bounded Praxis workflow](../openshell-praxis/openclaw.md).

## Verify runtime limits and policy

Confirm the runtime ceilings from the administrator account:

```bash
cd /
uid="$(id -u openshell-svc)"
sandbox=opencode-dev
container_id="$(
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  podman ps --filter name=openshell-default--"$sandbox" -q)"
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  podman inspect "$container_id" \
  --format 'cpus={{.HostConfig.NanoCpus}} memory={{.HostConfig.Memory}} pids={{.HostConfig.PidsLimit}}'
```

Use the selected sandbox name and expect the same two-CPU, 4 GiB, 2048-PID
limits used by the manual deployment.

To run the controlled policy qualification on a quickstart host, copy the
reviewed repository to a temporary service-readable location:

```bash
uid="$(id -u openshell-svc)"
reviewed_checkout="$HOME/secure-single-server"
sudo rm -rf /var/tmp/secure-single-server-policy
sudo install -d -m 0755 /var/tmp/secure-single-server-policy
for directory in openshell scripts configs; do
  sudo cp -a "$reviewed_checkout/$directory" /var/tmp/secure-single-server-policy/
done
sudo chown -R root:"$(id -gn openshell-svc)" /var/tmp/secure-single-server-policy
sudo chmod -R u=rwX,g=rX,o= /var/tmp/secure-single-server-policy
cd /
repo=/var/tmp/secure-single-server-policy
sudo runuser -u openshell-svc -- env HOME=/var/lib/openshell-svc \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  XDG_RUNTIME_DIR=/run/user/"$uid" \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus \
  OPENSHELL_BIN=/usr/bin/openshell \
  bash "$repo/openshell/tests/openshell-policy.sh"
sudo rm -rf /var/tmp/secure-single-server-policy
```

Follow the [harness checks](verification.md) after deployment. For optional model
routing, see the [OpenShell + Praxis guide](../openshell-praxis/README.md).
