# vLLM administration on RHEL

Install private Qwen inference on CPU or one NVIDIA L4, with cloud providers optional.
The preferred topology places vLLM on a separate server and gives Praxis a
private `RFC1918_IP:PORT` upstream. The older co-located container-network mode
remains available for compatibility but is deprecated for new deployments.

## Requirements

Use RHEL 9 x86_64 with SELinux enforcing. Step 2 prepares a new Praxis
gateway or reuses an installed memory/Valkey profile. Choose one backend:

- **GPU:** one NVIDIA L4, at least 32 GiB RAM and 200 GiB disk.
- **CPU:** AVX-512 and 100 GiB disk. Use 64 GiB RAM for quantized 27B;
  the 8B preset accepts 32 GiB, with 64 GiB recommended.

The installer pins the vLLM image and model revision, preserves downloaded
weights in the service account's cache, and binds remote mode only to the
selected private IPv4 address. One model runs at a time; changing the model
restarts only vLLM. Existing Praxis routes and cloud providers are retained.

| Model option | Weights and template | Intended use |
| --- | --- | --- |
| `qwen3-8b` (default) | Qwen3-8B BF16, pinned Qwen3 template, Hermes tool parser | Existing CPU/GPU baseline |
| `qwen3.8-27b-int4` | RedHatAI Qwen3.8-27B INT4, model revision's native template, Qwen XML tool parser | Larger text-only model; CPU/GPU qualification is recorded separately |

Both keep thinking enabled and one concurrent inference request.

| Mutable RHEL preset | Served context | OpenCode / Claude output, including thinking | Codex auto-compaction threshold |
| --- | --- | --- | --- |
| `qwen3-8b` | 16,384 | 4,096 | 12,288 |
| `qwen3.8-27b-int4` | 32,768 | 8,192 | 24,576 |

Context includes input and output. Codex's compaction headroom is not a separate
generation cap; Claude and OpenCode use their own compaction logic with the
configured context/output limits. Claude uses `medium` effort for Qwen3.8
because that model rejects `high`, and the launcher disables misleading 1M
context variants for local Qwen. CPU tasks can take minutes.

Short native tool tasks and model-switching checks passed on the 27B GPU preset
at 32,768 / 8,192. CPU qualification still uses the earlier 16,384 / 4,096 limits;
near-limit sessions and compaction remain unqualified on both.
These are deployment limits, not the model's native maximum. For full-context
hardware estimates and Flash variants, see [instance sizing](../../testing/aws.md#model-and-context-sizing).

The 27B preset uses quantized weights rather than the roughly 54 GB BF16
weights. Total runtime memory also includes cache and working buffers;
quantized model size alone is not a RAM/VRAM requirement.
[Model definition](../../../configs/vllm/qwen3.8-27b-int4.env),
[upstream quantization](https://huggingface.co/RedHatAI/Qwen3.8-27B-INT4).

## 1. Transfer the deployment files

From the reviewed checkout in a Bash or zsh workstation shell, select the
administrator login and key. Leave the key blank to use your SSH configuration
or agent. For separate servers, repeat this transfer on the gateway host and
the vLLM host:

```console
printf 'RHEL administrator login (user@host): '
IFS= read -r RHEL_HOST
printf 'SSH private-key path (Enter for SSH defaults): '
IFS= read -r SSH_KEY
SSH_OPTIONS=(-o ForwardAgent=no)
if [ -n "$SSH_KEY" ]; then SSH_OPTIONS+=(-o IdentitiesOnly=yes -i "$SSH_KEY"); fi
ssh "${SSH_OPTIONS[@]}" "$RHEL_HOST" \
  'install -d -m 0700 ~/secure-single-server-deploy/{configs,scripts,material}' &&
scp "${SSH_OPTIONS[@]}" -pr configs/common configs/all-in-one configs/remote-gateway configs/vllm \
  "$RHEL_HOST:~/secure-single-server-deploy/configs/" &&
scp "${SSH_OPTIONS[@]}" -pr scripts/common scripts/all-in-one scripts/remote-gateway scripts/vllm \
  "$RHEL_HOST:~/secure-single-server-deploy/scripts/"
```

Stop if a transfer fails. Connect and return to this directory after each login:

```console
ssh "${SSH_OPTIONS[@]}" "$RHEL_HOST"
```

The remaining commands run on RHEL:

```console
cd ~/secure-single-server-deploy
```

## 2. Prepare Praxis

Install host dependencies on the gateway host and, for separate-server mode,
on the vLLM host:

```console
sudo dnf install -y podman python3 python3-pyyaml openssl policycoreutils-python-utils jq curl
```

Prepare the locked service account on each host:

```console
sudo scripts/all-in-one/install --prepare
```

On a **dedicated inference host**, skip the rest of step 2 and install vLLM in
step 3. On the **gateway host**, skip gateway creation if Praxis is installed.
Otherwise choose one route, in the gateway's administrator terminal:

**Separate inference host (preferred):** enter its private IPv4 address and
port, for example `10.0.1.10:8000`. Permit port 8000 only from the gateway.

```console
printf 'Private vLLM endpoint (IPv4:8000): '
IFS= read -r VLLM_ENDPOINT
VLLM_ROUTE=(--vllm-endpoint "$VLLM_ENDPOINT")
```

**Co-located inference (existing single-VM workflow, deprecated):**

```console
VLLM_ROUTE=(--vllm)
```

For a new **all-in-one gateway**, install Valkey-backed Praxis with that route:

```console
sudo scripts/common/secret-set valkey v1 --generate &&
sudo scripts/all-in-one/install --profile valkey "${VLLM_ROUTE[@]}" \
  --valkey-image docker.io/valkey/valkey@sha256:63346cb24a61221e76bdf41acce99b3968a9fa83d8122144deab45394b27b4f2 \
  --valkey-url-secret praxis-valkey-url-v1 --valkey-acl-secret praxis-valkey-acl-v1
```

This needs no cloud key. For disposable memory quotas, replace the block above
with `sudo scripts/all-in-one/install --profile memory "${VLLM_ROUTE[@]}"`.

For **remote-gateway**, follow [gateway installation](../remote-gateway/install.md)
and select its Qwen option. It prepares TLS/JWT and the private gateway
before you install inference here. No cloud key is required for Qwen.

## 3. Install one backend

**GPU only:** prepare the driver and Container Toolkit, then reboot.

```console
sudo scripts/vllm/prepare-gpu
sudo systemctl reboot
```

Reconnect and run `cd ~/secure-single-server-deploy`. Select **one model**:

```console
VLLM_MODEL=qwen3-8b
```

Or select quantized Qwen3.8-27B:

```console
VLLM_MODEL=qwen3.8-27b-int4
```

On the **inference host**, select how vLLM binds:

**Separate host:** enter its assigned private IPv4 address (without a port).

```console
printf 'This inference host private IPv4 address: '
IFS= read -r VLLM_PRIVATE_IP
VLLM_BIND=(--remote "$VLLM_PRIVATE_IP")
```

**Co-located host:** keep vLLM only on the private container network.

```console
VLLM_BIND=()
```

Run only the command matching the inference hardware:

```console
# GPU:
sudo scripts/vllm/install --model "$VLLM_MODEL" "${VLLM_BIND[@]}" gpu
```

```console
# CPU:
sudo scripts/vllm/install --model "$VLLM_MODEL" "${VLLM_BIND[@]}" cpu
```

Use the verified private address from your infrastructure inventory. Workstation
shell variables are not transferred into an SSH session; set them on the host
as shown above.

To switch back, repeat with `VLLM_MODEL=qwen3-8b`. The old weights remain cached.
The model is selected during application installation; AWS VM configuration
continues to select hardware and gateway role.

Installation waits up to 30 minutes for the model. Repeating it preserves the
cache and replaces only its managed service/template. The GPU container alone
uses `SecurityLabelDisable` for CDI access; host SELinux remains enforcing.
Use the pinned image for your selected backend. An administrator can override
it with `--image NAME@sha256:DIGEST` after reviewing that release.

Back on the **gateway host**, verify it. If it was installed without Qwen,
enable the route first using the matching checkout and private endpoint:

```console
sudo scripts/common/providers enable vllm --vllm-endpoint "$VLLM_ENDPOINT"
sudo scripts/common/verify --host
```

Omit `--vllm-endpoint` only for the deprecated co-located mode. The provider
change is transactional and retains the existing gateway identity, secrets and
quota state.

Next, [share the vLLM quota and configure unified models](providers.md#share-the-local-vllm-quota-across-harnesses).
Add OpenAI, Anthropic or compatible providers there when ready.
For all-in-one, [create ordinary user logins](../all-in-one/accounts.md) and
follow [user setup](../all-in-one/users.md). Remote clients follow
[HTTPS/JWT user setup](../remote-gateway/users.md).

### Update an existing installation's budgets

Transfer the updated files from the same reviewed checkout, then rerun the
installer above for the installed model and backend. Wait for it to succeed
before refreshing the shared launcher on an all-in-one host:

```console
sudo install -m 0755 scripts/common/harness.py /usr/local/bin/praxis-harness
sudo install -m 0755 scripts/common/harness_config.py /usr/local/bin/praxis-harness-config
```

Update the [unified model catalog](providers.md#choose-cloud-models-and-apply)
to match the new preset and apply it. Ordinary users run `praxis-harness-config`
and restart their CLIs. Without unified mode, update the launcher on remote
clients too. Updating client limits alone does not increase server context.

## Inspect the backend

```console
sudo bash -c 'source scripts/common/lib.sh; as_service systemctl --user status praxis-vllm.service --no-pager'
sudo bash -c 'source scripts/common/lib.sh; as_service podman logs --tail 80 praxis-vllm'
sudo bash -c 'source scripts/common/lib.sh; as_service podman port praxis-vllm'
```

The port command prints only the private address in separate-server mode and
nothing in co-located mode. If the GPU driver is unavailable after a
kernel update, rerun `prepare-gpu`, reboot and repeat the install command with the intended `--model`.

## Remove vLLM

Enable another provider first if Qwen is your only one, then remove its routes
and backend:

```console
sudo scripts/common/providers disable vllm
sudo scripts/vllm/remove
```

Removal preserves downloaded images and model cache. To uninstall the entire
installation, remove vLLM before running `sudo scripts/common/uninstall`.
