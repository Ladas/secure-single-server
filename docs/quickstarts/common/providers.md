# Manage providers in an existing Praxis gateway

Run these commands in the administrator's RHEL SSH session, from the matching
deployment directory. They work for all-in-one and remote-gateway, with memory
or Valkey quotas. Qwen and other enabled providers remain available.

```console
cd ~/secure-single-server-deploy
sudo dnf install -y python3-pyyaml
sudo scripts/common/providers show
```

## How providers share the gateway

There is one Praxis service and one installed `/etc/praxis/shared-gateway.yaml`.
The installer and provider helper render it from the selected all-in-one or
remote-gateway template. Enabling vLLM adds routes to its private container;
enabling OpenAI/Anthropic adds cloud routes and secret references to the same
configuration. Existing listeners and remote TLS/JWT protection are preserved.

| Client API | All-in-one listener | Remote-gateway listener | Destination |
| --- | --- | --- | --- |
| `/vllm/v1/responses`, `/vllm/v1/chat/completions` | Loopback `8080` | HTTPS/JWT `8443` | Private vLLM |
| `/vllm/v1/messages` | Loopback `8081` | HTTPS/JWT `8443` | Private vLLM |
| `/v1/responses`, `/v1/chat/completions` | Loopback `8080` | HTTPS/JWT `8443` | OpenAI, when enabled |
| `/v1/messages` | Loopback `8081` | HTTPS/JWT `8443` | Anthropic, when enabled |

No extra public listener or manual YAML merge is needed. The renderer strips
`/vllm` before forwarding. `configs/vllm/praxis.yaml` is a separate bootc
profile; mutable RHEL installation does not combine it with the gateway YAMLs.
Use the matching deployment checkout: the helper rejects configuration drift.

## Add OpenAI

```console
sudo scripts/common/providers enable openai
```

Enter the API key at the hidden prompt in a private terminal without input
recording. The helper passes it through stdin into a Podman secret; it is not
placed in command arguments or copied to users. OpenAI serves Codex and OpenCode.

## Add Anthropic

This works independently of OpenAI:

```console
sudo scripts/common/providers enable anthropic
```

Enter its key at the hidden prompt. Anthropic serves Claude Code and OpenCode.

## Verify and give users access

```console
sudo scripts/common/providers show
sudo scripts/common/verify --host
```

Give users approved model IDs available to the provider account, never the
provider keys. Use [all-in-one user setup](../all-in-one/users.md) or
[remote client setup](../remote-gateway/users.md). Calls use the administrator's
provider account and its billing. The gateway forwards native APIs without translation.

## Rotate, disable or add local inference

Repeat `enable openai` or `enable anthropic` to rotate that key. To disable one
route while retaining its stored secret, choose the matching command:

```console
sudo scripts/common/providers disable openai
```

```console
sudo scripts/common/providers disable anthropic
```

Keep at least one provider enabled. To add local Qwen, follow
[vLLM installation](vllm.md); installing the model and enabling its route are
separate steps.

Provider changes preserve TLS/JWT settings and other providers. They restart
Praxis: memory quotas reset; Valkey token counters persist. Root and the service
account remain trusted with provider credentials.
