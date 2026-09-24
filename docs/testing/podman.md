# Test with one disposable Podman container

Use this path to inspect the configuration and make provider calls on a RHEL
box without installing a system service. It runs under the current user and is
not the shared-server deployment.

Configuration:
[`shared-gateway.yaml`](../../configs/all-in-one/shared-gateway.yaml).

Podman detaches the container from the terminal, so it normally continues
after an SSH disconnect. This is not a persistence guarantee: it does not
start at boot or recover after the container or host stops. Provider
credentials belong to the current user's environment and Podman process, not
a protected service account.

## 1. Install Podman

```console
sudo dnf install -y podman
cd secure-single-server
```

## 2. Select credentials

Export real credentials only for providers you intend to call. Both variables
must exist because the shipped configuration contains both provider chains.

```console
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
```

## 3. Start Praxis

```console
export PRAXIS_IMAGE='quay.io/opendatahub/praxis-experimental@sha256:a3006352106c2264427faa79b57cf7b49287f3f9bfffe9b2eef869d3429988e8'
podman pull "$PRAXIS_IMAGE"
podman run --replace --rm --detach --name praxis-dev \
  --user 1001:1001 \
  --userns keep-id:uid=1001,gid=1001 \
  --read-only \
  --security-opt no-new-privileges \
  --cap-drop all \
  --publish 127.0.0.1:8080:8080 \
  --publish 127.0.0.1:8081:8081 \
  --env OPENAI_API_KEY \
  --env ANTHROPIC_API_KEY \
  --volume "$PWD/configs/all-in-one/shared-gateway.yaml:/etc/praxis/shared-gateway.yaml:ro,Z" \
  "$PRAXIS_IMAGE" -c /etc/praxis/shared-gateway.yaml
```

## 4. Check it

```console
podman exec praxis-dev curl --fail --silent http://127.0.0.1:9901/healthy
podman port praxis-dev
```

Expected published ports are `127.0.0.1:8080` and `127.0.0.1:8081`. Admin port
`9901` is reachable only from inside the container.

Use the [user workflow](../quickstarts/all-in-one/users.md) to configure a harness, or
send a direct request:

```console
curl --fail-with-body http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer local-placeholder' \
  -d '{"model":"MODEL","messages":[{"role":"user","content":"hello"}]}'
```

Replace `MODEL` with a model accepted by the configured provider. An empty
provider credential lets Praxis start, but that provider will reject calls.

## 5. Inspect or stop it

```console
podman logs praxis-dev
podman stop praxis-dev
```

For boot startup, failure recovery, protected secrets, and an
administrator-owned policy, continue with the [in-memory deployment
quickstart](../quickstarts/all-in-one/in-memory.md) or the [Valkey deployment
quickstart](../quickstarts/all-in-one/valkey.md).
