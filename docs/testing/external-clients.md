# External remote-client acceptance

Run Codex, Claude Code and OpenCode on an ordinary user's **separate client**,
through HTTPS and a caller JWT to a remote-gateway installation. CPU/GPU refers
to the gateway's vLLM backend. The runner makes no SSH connection and receives
no issuer private key or upstream provider key. On-gateway harness passes do
not qualify this path.

The automated subset covers trusted TLS, rejection with an empty CA trust
store, missing/invalid JWTs, optional signed-expired JWTs, private-port reachability,
JSON/SSE APIs, native tool execution and independent tests of generated code.
Interactive selectors, resume, compaction, quota exhaustion/shared quota,
provider-side model attribution and host reboot remain separate acceptance rows.
It does not report the entire external-client matrix as passed.

## Prepare the gateway and client

Use [AWS deployment](aws.md) and [RHEL smoke testing](rhel-smoke.md) to prepare
a remote-gateway with synthetic providers. Complete mock acceptance before
[real Qwen setup](rhel-real.md). Use the matching reviewed checkout on both
machines; the test bundle includes `tests/remote-client/`. Do not run these
tests against the existing all-in-one installations.

On the separate client, install Python 3.9+, OpenSSL, Git and the pinned CLIs
from [remote user setup](../quickstarts/remote-gateway/users.md). Run as an
ordinary user. The runner creates a fresh project and isolated client home for
each harness, excluding personal provider settings, credentials and proxy
variables. Those automated sessions differ from normal interactive use.

## Export gateway evidence and caller material

After deploying/updating the gateway, run this **on the RHEL gateway** as its
administrator, from the transferred checkout:

```console
cd ~/secure-single-server-deploy
printf 'Gateway HTTPS origin, including port: '
IFS= read -r GATEWAY_URL
umask 077
sudo python3 tests/remote-client/server.py --url "$GATEWAY_URL" \
  > "$HOME/remote-server-evidence.json"
```

The export verifies the installed service and records its identity hash,
configuration hash, public TLS certificate fingerprint, JWT **public** key,
backend publication and actual CPU/GPU model/context. It exports no private
keys, provider credentials or configuration contents. For real Qwen, the server
must have the matching increased context before testing the updated launcher.
Copy the JSON to the client and start the run within an hour. The runner compares
the actual TLS certificate with this export and refuses the gateway's own
machine identity or a loopback URL. This is evidence supplied by the administrator,
not remote attestation of unchanged runtime throughout the test.

On the **administrator workstation**, issue test caller files with the existing
test issuer. Select and verify the intended VM before choosing its state directory:

```console
CLIENT_STATE="$PWD/.state/rhel-${RHEL_HOST/@/-}"
CALLER_MATERIAL="$CLIENT_STATE/external-$(date -u +%Y%m%dT%H%M%S)"
python3 tests/remote-client/issue.py --key "$CLIENT_STATE/issuer/private.pem" \
  --output "$CALLER_MATERIAL"
```

Copy only `caller.jwt`, `second.jwt`, `expired.jwt`, the public CA certificate
and the server evidence JSON to private files on the client. Keep the issuer
private key and all provider keys on the administrator/server side. The optional
negative fixture is actually signed and expired; an invalid signature alone
would not qualify expiration handling. The client checks signatures against
the exported public key before sending the fixtures.

## Run on the separate client

From its reviewed checkout, set paths to the received files:

```console
printf 'Gateway HTTPS origin, including port: '
IFS= read -r GATEWAY_URL
CLIENT_MATERIAL="$HOME/.config/praxis/external-test"
python3 tests/remote-client/run.py --url "$GATEWAY_URL" \
  --ca-file "$CLIENT_MATERIAL/ca.pem" --token-file "$CLIENT_MATERIAL/caller.jwt" \
  --second-token-file "$CLIENT_MATERIAL/second.jwt" \
  --expired-token-file "$CLIENT_MATERIAL/expired.jwt" \
  --server-evidence "$CLIENT_MATERIAL/server.json" \
  --mode mock --provider vllm --model qwen3-8b
```

For the mock cloud routes, repeat with `--provider openai --model fixture`
(Codex/OpenCode) and `--provider anthropic --model fixture` (Claude/OpenCode).
There is no API translation. The local synthetic vLLM fixture serves `qwen3-8b`;
that does not qualify real 8B or 27B inference.

After the administrator installs real Qwen and supplies a fresh evidence JSON,
repeat with `--mode real --provider vllm --model qwen3.8-27b-int4`, or the
installed 8B alias. Automated real cloud calls are refused. Real deadlines are
60 minutes per CPU harness and 30 per GPU harness; mocks have three minutes.
Use `--harness codex|opencode|claude` to narrow a rerun. `--output` chooses a
new evidence directory and refuses an existing one.

Default private evidence is `.state/external-client-TIMESTAMP/`: `result.json`,
redacted CLI logs, isolated homes and generated projects. Results record the
gateway evidence hash, launcher/runner hashes, CLI versions, durations and
the exact automated subset. Nonzero exits, timeouts, missing successful tool
events, empty tests or wrong functions fail qualification. Cancellation stops
the harness process group. The optional second subject proves a separate
successful caller request, **not shared-quota semantics**.

## Complete the remaining matrix

| Dimension | Required runs |
| --- | --- |
| Gateway/backend | Remote CPU and remote GPU; memory and Valkey recorded separately |
| Provider/model | Synthetic local and cloud routes first; real 8B/27B recorded separately |
| Harness | Codex, Claude Code, OpenCode on each supported native route |
| Configuration | Isolated automated launcher run; separate normal interactive and file-config runs |
| Model selector | Open `/model` or `/models`, select the approved ID, execute a task and retain actual provider request evidence |
| Quotas | Two signed subjects share one allowance, exhaustion and recovery, denial between tool calls; follow Q1–Q10 |
| Lifecycle | Fresh task after gateway restart/reboot; client restart and resume recorded separately |

Use [manual harness acceptance](harnesses.md) and
[gateway feature testing](gateway-features.md) for the remaining cases. Server
health, an API model list and a client banner are insufficient to prove actual
harness request attribution. Retain sanitized provider/backend observations
beside client results and leave attribution unverified when absent.
Update only matching [compatibility cells](compatibility.md#remote-gateway)
after collecting real external-client evidence. No RHEL external-client pass
is claimed by this implementation or its local TLS/unit tests.
