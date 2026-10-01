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

The recorded 27B RHEL passes used the earlier 16,384 / 4,096 budgets. The larger
budgets require a fresh CPU/GPU run, including long-session compaction and tool
continuation. See the [result ledger](../../testing/compatibility.md#cpugpu-limits-and-measured-performance).
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

On a dedicated vLLM host, run only the preparation command below and do not
install the gateway. On the gateway host, continue with the selected gateway
installation.

Skip gateway creation if Praxis is already installed. For a new **all-in-one**
gateway with memory quotas:

```console
sudo scripts/all-in-one/install --prepare
sudo scripts/all-in-one/install --profile memory --vllm-endpoint "$VLLM_ENDPOINT"
```

For persistent all-in-one quotas, use the [Valkey profile](../all-in-one/valkey.md)
with `--vllm` instead of `--openai-secret` / `--anthropic-secret`. The three
Valkey arguments remain required.

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

Then install on the matching hardware:

```console
# GPU:
sudo scripts/vllm/install --model "$VLLM_MODEL" --remote "$VLLM_PRIVATE_IP" gpu
```

```console
# CPU:
sudo scripts/vllm/install --model "$VLLM_MODEL" --remote "$VLLM_PRIVATE_IP" cpu
```

On AWS, obtain `VLLM_PRIVATE_IP` and `VLLM_ENDPOINT` from
[the private endpoint helper](../../testing/aws.md#separate-vllm-server). The
helper requires the dedicated instance to carry the launcher's ownership and
`vllm-server` tags, and it rejects public port-8000 ingress.

To switch back, repeat with `VLLM_MODEL=qwen3-8b`. The old weights remain cached.
The model is selected during application installation; AWS VM configuration
continues to select hardware and gateway role.

Installation waits up to 30 minutes for the model. Repeating it preserves the
cache and replaces only its managed service/template. The GPU container alone
uses `SecurityLabelDisable` for CDI access; host SELinux remains enforcing.
Use the pinned image for your selected backend. An administrator can override
it with `--image NAME@sha256:DIGEST` after reviewing that release.

If Praxis was installed without Qwen, enable its routes using the matching
checkout:

```console
sudo scripts/common/providers enable vllm --vllm-endpoint "$VLLM_ENDPOINT"
sudo scripts/common/verify --host
```

Omit `--vllm-endpoint` only for the deprecated co-located mode. The provider
change is transactional and retains the existing gateway identity, secrets and
quota state.

Optionally [add OpenAI and Anthropic](providers.md) without replacing Qwen.
For all-in-one, [create ordinary user logins](../all-in-one/accounts.md) and
follow [user setup](../all-in-one/users.md). Remote clients follow
[HTTPS/JWT user setup](../remote-gateway/users.md).

### Update an existing installation's budgets

Transfer the updated files from the same reviewed checkout, then rerun the
installer above for the installed model and backend. Wait for it to succeed
before refreshing the shared launcher on an all-in-one host:

```console
sudo install -m 0755 scripts/common/harness.py /usr/local/bin/praxis-harness
```

Restart interactive harness sessions so they load the new limits. Remote
clients must update their launcher copy too. Updating a client alone does not
increase the server's context. The RHEL `real-test` phase also refreshes the
shared launcher, but it does not reinstall vLLM; rerun `real-setup` first on a
matching test installation without real cloud credentials. Preserve manual
projects and earlier result files.

## Inspect the backend

```console
sudo bash -c 'source scripts/common/lib.sh; as_service systemctl --user status praxis-vllm.service --no-pager'
sudo bash -c 'source scripts/common/lib.sh; as_service podman logs --tail 80 praxis-vllm'
sudo bash -c 'source scripts/common/lib.sh; as_service podman port praxis-vllm'
```

The port command should print nothing. If the GPU driver is unavailable after a
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
