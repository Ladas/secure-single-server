# External remote-client acceptance

Test that your locally installed Codex, Claude Code and OpenCode can connect to
Praxis using its HTTPS URL and your caller JWT. A valid token must let the harness
complete a small coding task on your machine. Missing, invalid and expired tokens
must be rejected by the gateway. Provider credentials stay on the server.

## Test locally with Podman

Install the pinned CLIs from [client setup](../quickstarts/remote-gateway/users.md#2-prepare-the-client),
then run from this checkout as your ordinary user. Start the Podman VM on macOS
if it is stopped:

```console
podman machine start
python3 -B tests/remote-client/local.py
```

On Linux, start the local Podman service as needed; no Podman VM is required.
The test starts a disposable Praxis gateway with a temporary CA and JWT issuer.
Only its HTTPS endpoint and test control endpoint are published on loopback.
The model is a deterministic fixture; no model download or provider key is needed.

The test checks TLS trust and rejects missing, malformed, incorrectly signed,
expired, wrong-issuer and wrong-audience JWTs on each supported inference API.
It verifies that denied requests do not reach the model. Each working
harness/provider pair then uses the same launcher as the remote test, receives
streamed tool calls, writes a tiny project and runs its tests. Independent
checks verify the generated function and the recorded model requests.

Use `--provider vllm --harness claude` for a narrower run. `--api-only` runs TLS,
JWT and inference API checks without starting harnesses. `--valkey` selects that
gateway storage profile. Private logs and projects stay under
`.state/local-remote-client-TIMESTAMP/`; owned containers are removed afterward.
This validates local gateway authentication and client setup before the RHEL run.

### Harness/provider matrix

Every provider includes all three harnesses in the result. Current local results
use synthetic models behind the real gateway:

| Harness | vLLM | OpenAI | Anthropic |
| --- | --- | --- | --- |
| Codex | Passed | Passed | Blocked: Responses-to-Messages translation |
| Claude Code | Passed | Blocked: Messages-to-OpenAI translation | Passed |
| OpenCode | Passed | Passed | Passed |

Blocked entries retain their reason in the evidence and are never counted as
passes. The gateway routes and launcher must integrate the required translation
before those entries can run. A run with blocked or unrun harnesses reports
`partial`; `--api-only` reports only the API result and leaves harnesses unrun.
The same complete matrix is used for RHEL testing.

## Configure your own local harness

For normal use, obtain the HTTPS URL, an approved model ID, your caller JWT and
any private CA certificate from the administrator. Follow
[remote user setup](../quickstarts/remote-gateway/users.md) to launch your chosen
harness with `--url`, `--token-file` and, for a private CA, `--ca-file`.
The launcher sets the following for local Qwen:

| Harness | Endpoint | Caller JWT configuration |
| --- | --- | --- |
| Codex | `https://GATEWAY/vllm/v1`, Responses API | `PRAXIS_PLACEHOLDER_KEY`, referenced by the Praxis provider's `env_key` |
| Claude Code | `https://GATEWAY/vllm`, Messages API | `ANTHROPIC_AUTH_TOKEN` |
| OpenCode | `https://GATEWAY/vllm/v1`, Chat Completions API | Praxis provider `apiKey` and `Authorization: Bearer` header |

Files and tools run on your client. The gateway only handles inference.
The server evidence export below is for automated qualification; ordinary
harness use needs the connection details and caller token, without that export.

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
and `--provider anthropic --model fixture`. Each includes all three harnesses;
the translation cases above are recorded as blocked. The local synthetic vLLM fixture serves `qwen3-8b`;
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
the harness process group. The optional second subject checks that another
issued caller can also authenticate.

## Record the RHEL result

For each supported harness, record whether the valid JWT completes the tool task,
which invalid-token cases return `401`, and whether TLS verification succeeds
with the supplied CA. Repeat the same client setup against the deployed remote
gateway. Update the [remote-gateway results](compatibility.md#remote-gateway)
only after that run; local Podman results do not establish RHEL deployment health.
