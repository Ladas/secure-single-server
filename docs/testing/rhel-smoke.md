# RHEL smoke tests

Start after [AWS deployment](aws.md). Keep `ALL_IN_ONE_HOST`,
`REMOTE_GATEWAY_HOST` and `SSH_KEY` in your workstation terminal. Verify each
SSH host key and unlock your key with `ssh-add` before automation.

The runner installs Praxis and real Codex, OpenCode and Claude CLIs, then tests
private mocked vLLM, OpenAI and Anthropic providers. No real provider key is
needed. The administrator installs services; the runner creates `praxis-smoke`
and runs CLIs as that ordinary account, without sudo or access to service
configuration. SSH agent forwarding is disabled. For interactive work afterward,
[create a separate personal login](../quickstarts/all-in-one/accounts.md).

## 1. Install and test

Run from the checkout on your workstation:

```console
python3 tests/rhel/run.py --host "$ALL_IN_ONE_HOST" --ssh-key "$SSH_KEY" \
  --scenario all-in-one --profile memory
```

```console
python3 tests/rhel/run.py --host "$REMOTE_GATEWAY_HOST" --ssh-key "$SSH_KEY" \
  --scenario remote-gateway --profile memory
```

Each command checks installation, JSON/SSE, native tool execution and generated
tests. It exercises Qwen-only operation, then independent OpenAI and Anthropic
additions, disabled routes and backend failure without cloud fallback.
Remote-gateway also checks public TLS and JWT rejection/acceptance.

Both VMs need RHEL 9, enforcing SELinux, cgroups v2 and outbound package/image
access. GPU drivers are unnecessary for mocks. The runner refuses unrelated
installations and real cloud secrets. Fix any nonzero result before continuing;
rerun the same command to resume the matching mock installation.

## 2. Check reboot recovery

These commands reboot the VMs, verify a changed boot ID and repeat host/CLI checks:

```console
python3 tests/rhel/run.py --host "$ALL_IN_ONE_HOST" --ssh-key "$SSH_KEY" \
  --scenario all-in-one --phase lifecycle
```

```console
python3 tests/rhel/run.py --host "$REMOTE_GATEWAY_HOST" --ssh-key "$SSH_KEY" \
  --scenario remote-gateway --phase lifecycle
```

## 3. Choose the next test

For real Qwen, continue to [real-provider setup](rhel-real.md).
Its `real-setup` phase removes mocks and synthetic cloud secrets. Existing VMs
can be reused; fresh VMs are optional.

### Optional Valkey

To repeat the suite with durable quotas:

```console
python3 tests/rhel/run.py --host "$ALL_IN_ONE_HOST" --ssh-key "$SSH_KEY" \
  --scenario all-in-one --profile valkey --phase switch-profile
```

```console
python3 tests/rhel/run.py --host "$REMOTE_GATEWAY_HOST" --ssh-key "$SSH_KEY" \
  --scenario remote-gateway --profile valkey --phase switch-profile
```

Repeat lifecycle checks with `--profile valkey`, and retain that option for
subsequent real-provider commands. Profile switching applies only to the
runner's mock installation and preserves existing secrets/Valkey data.

### Optional OpenShell

Reuse all-in-one after its native mock suite passes:

```console
python3 tests/rhel/run.py --host "$ALL_IN_ONE_HOST" --ssh-key "$SSH_KEY" \
  --scenario all-in-one --profile memory --phase openshell
```

Use `--profile valkey` instead if installed. This experimental addon has a
separate service account and tests a sandbox API request and policy enforcement.
It does not yet repeat the native CLI file/test task inside the sandbox.
Run it before switching to real providers; a third VM is unnecessary.
For real Qwen experiments afterward, use [manual OpenShell testing](openshell-manual.md).

## Logs and diagnostics

Workstation: `.state/rhel-USER-HOST/`. VM: `/var/lib/praxis-rhel-smoke/`.
Logs contain redacted results and bundle hashes; private CA/JWT signing keys
stay on the workstation. Services remain running after a failure.

Use `--phase check` for host checks, `--phase test` for baseline mock contracts
and CLIs, or `--phase providers` for the full provider-addition sequence.
Do not enter real keys into a mock installation.
