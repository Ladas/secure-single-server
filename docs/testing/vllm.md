# vLLM administration on RHEL

For the automated AWS workflow, follow [real-provider testing](rhel-real.md).
This guide installs or maintains private Qwen3-8B without the smoke runner.
Run commands from the repository root on the RHEL VM.

## Requirements

Use RHEL 9 x86_64 with SELinux enforcing and an installed Praxis memory or
Valkey profile. Choose one backend:

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
small-machine smoke settings, not the model's maximum context or a guarantee
of cloud-model quality. See the [matrix](compatibility.md#thinking-mode).

## Prepare a fresh Praxis installation

Skip this section if Praxis is installed. Transfer the reviewed `configs/`,
`scripts/` and `tests/` directories into a private administrator checkout first.
Install host dependencies:

```console
sudo dnf install -y podman python3 python3-pyyaml openssl policycoreutils-python-utils jq curl
```

**All-in-one, memory quotas:**

```console
sudo scripts/all-in-one/install --prepare
sudo scripts/all-in-one/install --profile memory --vllm
```

**Remote-gateway, memory quotas:** prepare TLS and the public JWT key using
[remote-gateway installation](../quickstarts/remote-gateway/install.md#1-prepare-administrator-material),
then run:

```console
chmod 600 material/tls-key.pem
sudo scripts/remote-gateway/install --prepare
sudo scripts/remote-gateway/install --profile memory --vllm \
  --tls-cert material/tls.pem --tls-key material/tls-key.pem \
  --jwt-public-key material/jwt-public.pem
```

Neither command needs cloud credentials. For persistent quotas, select
`--profile valkey` and the three `--valkey-*` arguments from the
[Valkey guide](../quickstarts/all-in-one/valkey.md). Continue with one backend.

## Install one backend

**GPU only:** prepare the driver and Container Toolkit, then reboot.

```console
sudo scripts/vllm/prepare-gpu
sudo systemctl reboot
```

Reconnect, return to the checkout and install:

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
For controlled version comparisons, `--image NAME@sha256:DIGEST` overrides
only the backend image. Use the [candidate testing guide](vllm-debugging.md#compare-a-vllm-candidate)
before changing default pins.

If Praxis was installed without Qwen, enable its routes using the matching
checkout:

```console
sudo scripts/common/providers enable vllm
sudo scripts/common/verify --host
```

Optionally [add OpenAI and Anthropic](rhel-real.md#3-add-openai-to-existing-praxis)
without replacing Qwen. For all-in-one, [create ordinary user logins](../quickstarts/all-in-one/accounts.md)
and follow [user setup and usage](../quickstarts/all-in-one/users.md). Remote
clients follow the [HTTPS/JWT harness guide](harnesses.md).

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
