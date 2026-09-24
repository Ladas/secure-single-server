# Accept the in-memory and Valkey profiles with real harnesses

Run this checklist for **both scenarios**, first on a full local Fedora/RHEL
VM, then on the two AWS RHEL VMs. Use the same reviewed revision. This round
covers Codex, OpenCode and Claude Code with memory and Valkey token quotas;
Switchyard is the next phase. Fedora results do not qualify RHEL.

| Scenario | Harness runs | Setup |
| --- | --- | --- |
| All-in-one | Two ordinary RHEL accounts | [On-box user setup](../quickstarts/all-in-one/users.md), loopback and placeholders |
| Remote gateway | Mac or another test host, two caller JWTs | [Remote user setup](../quickstarts/remote-gateway/users.md), HTTPS and trusted certificate |

These tests make paid provider calls and execute model-proposed commands.
Use dedicated test credentials, disposable projects, and ordinary OS accounts
without sudo. Keep normal harness approval/sandbox controls enabled.

## 1. Prepare the host and keys as administrator

Complete the no-key [local RHEL VM checks](rhel-vm.md) first. On AWS, follow
the selected scenario in the [two-VM guide](aws.md). The Fedora
CoreOS Podman machine is only the image-check stage; it does not test this
locked-account deployment.

Use separate revocable provider keys for the local and AWS hosts. Apply the
provider's available project restrictions and usage alerts. Never copy keys
into the repository, a user account, a harness configuration, or test evidence.

| Harness | Listener | Real credential stored by administrator |
| --- | --- | --- |
| Codex | OpenAI Responses, `127.0.0.1:8080/v1` | OpenAI key with access to the chosen Responses model |
| OpenCode | Chat Completions, `127.0.0.1:8080/v1` | OpenAI key with access to the chosen Chat Completions model |
| Claude Code | Anthropic Messages, `127.0.0.1:8081` | Anthropic key with access to the chosen Claude model |

For the remote gateway, replace the two listener origins with the same
`https://GATEWAY:8443`: Codex/OpenCode use `/v1`, Claude Code uses the origin.
The provider secrets remain on the gateway. Users receive caller JWTs only.

OpenAI credentials alone cannot complete Claude Code acceptance. Mark that
row **blocked**, not passed, until the Anthropic credential is available.

Follow the quickstart's hidden-input prompts to store keys as versioned
Podman secrets. Those steps disable shell tracing/automatic export, pass
keys over stdin, and unset the temporary variables. Use a private terminal
without session/input recording. Do not use `env`, `set`, `printenv`, raw
container inspection, or shell tracing to collect evidence.

If the VM has the dummy `vm1` secrets from its no-key test, create real `v1`
secrets using the quickstart and apply them from the administrator bundle:

The command below is for **all-in-one memory**. For the remote scenario,
rerun its complete install command with new secret names and `--replace`,
including the TLS/public-key paths. Include `--development-fedora` on Fedora.

```console
sudo scripts/common/upgrade --profile memory \
  --openai-secret praxis-openai-api-key-v1 \
  --anthropic-secret praxis-anthropic-api-key-v1
sudo scripts/common/status
sudo scripts/common/verify --host
```

Use new version names if `v1` already exists; the helper never overwrites an
existing secret. Root and `praxis-svc` remain trusted. Podman secrets isolate
credentials from ordinary users; they are not an encrypted external vault.

Install the test-project dependencies on both RHEL hosts:

```console
sudo dnf install -y git python3 curl jq tar gzip tmux
```

For all-in-one, provide two separate ordinary accounts and SSH access. Neither
account may have sudo, membership in the `praxis-svc` group, or a shared admin
login. Supply accepted model IDs; do not assume one model supports all APIs.

## 2. Test each harness as an ordinary user

Follow the selected scenario's user setup from the table above. All-in-one
uses loopback and a placeholder; remote uses HTTPS and a caller JWT.
Do not log into the harness with a personal provider
key or subscription. Use clean test accounts without conflicting saved
provider settings. Existing administrator-managed settings must be checked
before testing.

For each harness/profile combination, create a fresh private project:

```console
TEST_PROJECT="$(mktemp -d "$HOME/praxis-smoke.XXXXXX")"
cd "$TEST_PROJECT"
git init -q
```

Start the harness using its command in the user workflow. Give it this task:

```text
Create add.py with an add(a, b) function and test_add.py using Python unittest.
Test positive numbers, negative numbers, and zero. Run python3 -m unittest -v
and fix any failures. Use only the Python standard library. Do not install
packages, access credentials, or modify anything outside this project.
```

Approve only the expected local file and test commands. Acceptance requires
streamed output, file/tool operations, and passing tests—not just a greeting.
After leaving the harness, confirm independently:

```console
test -f add.py && test -f test_add.py && python3 -m unittest -v
```

The administrator should correlate the run with successful requests in the
Praxis service journal, reviewing it locally and redacting before sharing.
Also check provider usage for the dedicated test project. A working harness
alone does not prove every token was reconciled correctly: retain
accounting/limit verification as a separate acceptance item below.

Repeat the task from the second OS account. Both users must reach Praxis and
share the same per-protocol allowance without receiving real credentials.
For the remote scenario, repeat from the second caller JWT instead. Also
complete the [TLS/JWT negative checks](remote-gateway.md); the remote caller
needs no OS account on the gateway.
Check denied access from each ordinary account:

```console
for path in /etc/praxis/shared-gateway.yaml /var/lib/praxis-svc; do
  if test -r "$path" || test -w "$path"; then
    printf 'FAIL: unexpected access to %s\n' "$path"
  else
    printf 'PASS: protected %s\n' "$path"
  fi
done
```

This is a focused permissions check, not a full isolation/security audit.
The file-permission commands apply on the all-in-one host. On the remote
gateway, use an ordinary test SSH account only for the host-isolation audit;
normal remote harness users do not receive SSH access.

## 3. Repeat with Valkey

After recording the in-memory results, stop the harnesses. As administrator,
remove only the installed profile; secrets and Valkey data are preserved:

```console
sudo scripts/common/uninstall
```

Follow the [Valkey quickstart](../quickstarts/all-in-one/valkey.md), reusing the real `v1`
provider secrets and creating the generated Valkey credentials. Repeat the
same three harness tests and user-separation checks. Client URLs and
placeholder credentials do not change. Do not combine the two profiles or
purge Valkey data during persistence testing. For the remote gateway, use
its [Valkey install command](../quickstarts/remote-gateway/install.md#3-install-persistent-token-quotas)
instead; the HTTPS URL, CA and JWT remain unchanged.

## 4. Lifecycle, limits, and accounting gates

Perform disruptive checks only on these dedicated test hosts, with no other
users' work running. Do not count `verify --host` alone as logout/reboot,
isolation, or token-accounting acceptance.

| Check | Required result |
| --- | --- |
| SSH logout/reconnect | Praxis remains available; users reconnect and resume their harness using its supported workflow |
| Host reboot | Service starts without an administrator login; host verification and a fresh harness request succeed |
| Request rate limit | Both users share the configured per-chain request bucket; excess traffic receives a local 429 |
| Token admission/accounting | For Responses, Chat Completions, and Messages, verify reported usage and reservation settlement, including streaming/tool turns; confirm local 429 when allowance is insufficient |
| In-memory restart | After confirmed usage, restarting Praxis resets the token allowance |
| Valkey restart | After confirmed usage, restarting Praxis retains token usage; restarting Valkey/host retains persisted usage within the documented AOF durability window |
| Key separation | Ordinary users cannot read configuration, service storage, or credentials, or control the service account |

The shipped allowance is 1,000,000 tokens per rolling 24 hours, reserving
10,000 per request. Do not spend that allowance merely to trigger rejection.
Use a reviewed small-limit configuration on the disposable host for limit
tests, keeping the reservation within the capacity. Record the exact diff
and the accounting evidence. The no-key Valkey test proves ACL/AOF behavior;
it does **not** prove Praxis-to-Valkey token reconciliation. These end-to-end
limit/persistence checks are still manual qualification work.

## 5. Record results and clean up

Record each cell as pass, fail, or blocked with the date, tested commit,
host/image architecture, image digest, Podman version, harness version,
model ID, and a short redacted result. Missing credentials are blocked tests.

Record this matrix **separately for each scenario and host OS**:

| Harness | Local arm64 memory | Local arm64 Valkey | AWS amd64 memory | AWS amd64 Valkey |
| --- | --- | --- | --- | --- |
| Codex | Pending | Pending | Pending | Pending |
| OpenCode | Pending | Pending | Pending | Pending |
| Claude Code | Pending | Pending | Pending | Pending |

Also record the lifecycle/limits gates separately for each host/profile.
An AWS Graviton instance tests arm64 instead; it does not cover amd64.

Revoke the dedicated provider keys when testing ends. Terminating an EC2
instance does not revoke provider keys or remove copied VM snapshots.
Keep evidence free of credentials and private prompt/project content.
