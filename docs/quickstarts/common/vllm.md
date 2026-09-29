# vLLM administration on RHEL

Install private Qwen3-8B on CPU or one NVIDIA L4, with cloud providers optional.
The administrator manages inference; ordinary users run their own harnesses.

## Requirements

Use RHEL 9 x86_64 with SELinux enforcing. Step 2 prepares a new Praxis
gateway or reuses an installed memory/Valkey profile. Choose one backend:

- **GPU:** one NVIDIA L4, at least 32 GiB RAM and 200 GiB disk.
- **CPU:** AVX-512, at least 32 GiB RAM; 64 GiB RAM and 100 GiB disk recommended.

The installer uses pinned vLLM images, model revision and chat template from
`configs/vllm/`. It downloads model weights into the service account's persistent
cache. vLLM joins Praxis's private container network; port 8000 is never
published on the host. `qwen3.jinja` preserves the pinned model template's
thinking-enabled default; the server uses the `qwen3` reasoning parser and
`hermes` tool parser. The harness launcher configures Qwen's reasoning format
and 16k context; OpenCode and Claude reserve up to 4096 output tokens, including
thinking. Long reasoning can exhaust that budget before answering. These are
deployment defaults, not the model's maximum context. CPU tasks can take
several minutes. Start with OpenCode; GPU is faster for interactive use.
Thinking does not imply the same answers or reliability as a cloud model.

## 1. Transfer the deployment files

From the reviewed checkout in a Bash or zsh workstation shell, select the administrator login
and key. Leave the key blank to use your SSH configuration or agent:

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

Install host dependencies:

```console
sudo dnf install -y podman python3 python3-pyyaml openssl policycoreutils-python-utils jq curl
```

Skip gateway creation if Praxis is already installed. For a new **all-in-one**
gateway with memory quotas:

```console
sudo scripts/all-in-one/install --prepare
sudo scripts/all-in-one/install --profile memory --vllm
```

For persistent all-in-one quotas, use the [Valkey profile](../all-in-one/valkey.md)
with `--vllm` instead of `--openai-secret` / `--anthropic-secret`. The three
Valkey arguments remain required.

For **remote-gateway**, follow [gateway installation](../remote-gateway/install.md)
and select its local Qwen option. It prepares TLS/JWT and the private gateway
before you install inference here. No cloud key is required for Qwen.

## 3. Install one backend

**GPU only:** prepare the driver and Container Toolkit, then reboot.

```console
sudo scripts/vllm/prepare-gpu
sudo systemctl reboot
```

Reconnect, run `cd ~/secure-single-server-deploy`, then install:

```console
nvidia-smi
sudo scripts/vllm/install gpu
```

**CPU only:**

```console
sudo scripts/vllm/install cpu
```

Installation waits up to 30 minutes for the model. Repeating it preserves the
cache and replaces only its managed service/template. The GPU container alone
uses `SecurityLabelDisable` for CDI access; host SELinux remains enforcing.
Use the pinned image for your selected backend. An administrator can override
it with `--image NAME@sha256:DIGEST` after reviewing that release.

If Praxis was installed without Qwen, enable its routes using the matching
checkout:

```console
sudo scripts/common/providers enable vllm
sudo scripts/common/verify --host
```

Optionally [add OpenAI and Anthropic](providers.md) without replacing Qwen.
For all-in-one, [create ordinary user logins](../all-in-one/accounts.md) and
follow [user setup](../all-in-one/users.md). Remote clients follow
[HTTPS/JWT user setup](../remote-gateway/users.md).

## Inspect the backend

```console
sudo bash -c 'source scripts/common/lib.sh; as_service systemctl --user status praxis-vllm.service --no-pager'
sudo bash -c 'source scripts/common/lib.sh; as_service podman logs --tail 80 praxis-vllm'
sudo bash -c 'source scripts/common/lib.sh; as_service podman port praxis-vllm'
```

The port command should print nothing. If the GPU driver is unavailable after a
kernel update, rerun `prepare-gpu`, reboot and repeat `install gpu`.

## Remove vLLM

Enable another provider first if Qwen is your only one, then remove its routes
and backend:

```console
sudo scripts/common/providers disable vllm
sudo scripts/vllm/remove
```

Removal preserves downloaded images and model cache. To uninstall the entire
installation, remove vLLM before running `sudo scripts/common/uninstall`.
