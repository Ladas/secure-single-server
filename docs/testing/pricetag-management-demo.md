# Management demo on RHEL

**Candidate workflow — fresh installation and browser scenarios verified on RHEL.** Use a dedicated
benchmark VM and the matching PriceTag management candidate. Published PriceTag
images do not yet contain these management APIs. All inference is synthetic.

## Prepare images

Run on the RHEL VM from this checkout. Set `METERING_SOURCE` to the reviewed
PriceTag candidate source directory. Build or pull matching standalone MaaS and
Praxis images using the [installation guide](../quickstarts/remote-gateway-pricetag/README.md).
Keep these images in root's Podman store. Get their immutable IDs:

```sh
export REPO="$PWD"
sudo podman build -f "$REPO/configs/pricetag/Containerfile.metering" \
  -t localhost/pricetag-metering:management-candidate "$METERING_SOURCE"
sudo podman images --no-trunc
```

## Install the mock gateway

Set the public hostname and three image IDs from the previous step. The installer
imports them into the service account, prepares the Quadlets, starts the services,
and keeps provider configuration host-managed. It refuses existing data. The reduced PriceTag image does not include provider/model editing in the browser.

```sh
sudo "$REPO/scripts/pricetag/install-demo" \
  --hostname "$GATEWAY_HOST" \
  --praxis-image "$PRAXIS_IMAGE_ID" \
  --maas-image "$MAAS_IMAGE_ID" \
  --metering-image "$METERING_IMAGE_ID"
```

Append `--plan` to inspect the steps without changing the host. Installation uses
synthetic credentials only. Keep TCP 8443 restricted to the testing IPs while
qualifying the candidate; database and management ports remain private.

## Prepare the live UI demo

1. Sign in at `https://<gateway-host>:8443/login` using the administrator key at
   `/root/pricetag-admin/admin.key`. Transfer/display keys only in a private terminal.
2. Open **Account management → Model pricing**. Configure illustrative rates for
   upstream IDs `fixture` and `fixture-cheap`; label them synthetic. For example,
   USD/MTok input/output rates of 1,000/2,000 and 100/200 make the mock differences
   visible. Set both cache rates explicitly. These are demo rates, not vendor prices.
3. Create the 20-user, two-team fixture. The script creates finite keys through
   APIs and generates mock usage; it does not write business tables directly.

```sh
cd "$REPO"
sudo python3 tests/pricetag/rhel-demo-fixture.py \
  --output /root/pricetag-admin/demo-team-fixture
```

Use `--resume` with the same arguments after an interrupted fixture run. Private
keys and its progress manifest remain in the output directory. Resume skips
recorded successful traffic; it is not an exactly-once workload after a crash.

Perform live user/team, key, budget and pricing changes in the UI. Prepare provider/model routes before the demo using the host workflow.
Fixture generation and automated assertions may use APIs. Do not use terminal
management as a substitute for a missing demo UI.

## Qualification scope

The reduced six-commit image has per-commit Go/PostgreSQL coverage. The browser
suite below was qualified with the larger image; several checks use its gateway
configuration API as a mock guard and are **not yet adapted to the reduced image**.
Do not report that historical 17-stage result as a pass for this reduced install.

The optional `--gateway-management` installer flag is only for a full image that
implements the adapter API. It is not required for the reduced storyboard's user,
budget, price and scoped-dashboard controls.

## Automated checks

The `tests/pricetag/browser-*.cjs` scripts use Playwright and require a private key
directory, the server certificate, `GATEWAY_URL`, and explicit
`MOCK_DEPLOYMENT_CONFIRMED=yes`. They verify mock-only endpoints before mutations.
For `browser-session-boundary.cjs`, also set `NODE_EXTRA_CA_CERTS` to the copied
server CA file: its API client verifies TLS separately from Chromium. Never
enable traces or screenshots while one-time keys are displayed.

Current tests cover onboarding, team isolation, provider activation, prices and
budget exceptions, discounts, offboarding, and finite-key lifecycle. They leave
synthetic account/ledger data. Fixture cleanup suspends demo users and revokes their fixture keys while retaining
accounting history. Use a new prefix and output directory for the next dataset.
A forced gateway start failure passed browser rollback verification, including
restored catalog and authenticated inference. Forced process interruption after the first configuration write also recovered all
six files on daemon restart. Final security review remains; this is not a
release-qualified deployment.

```sh
sudo python3 tests/pricetag/rhel-demo-fixture.py --cleanup \
  --output /root/pricetag-admin/demo-team-fixture
```

## Quota safety matrix

Run on an idle mock deployment. This API test seeds labelled synthetic usage,
checks two users against the global USD exception and a third against the 10B
monthly token gate, then restores the policy and suspends its identities.
The retained synthetic ledger includes 10B zero-priced tokens; exclude these test
identities from presentation data. This is enforcement verification, not a live
UI scene; `browser-pricing.cjs` exercises the browser controls.

```sh
sudo python3 tests/pricetag/rhel-quota-matrix.py \
  --output /root/pricetag-admin/quota-matrix
```

Use a new output directory each run. The original non-secret policy and sanitized
observations are saved there. An exception is global and names the upstream model
ID; it bypasses USD denial only, not the token safety gate. An exception need not
be free, so choose its price deliberately.

Check the public route boundary without changing configuration:

```sh
sudo python3 tests/pricetag/rhel-public-boundary.py
```

This checks anonymous/spoofed identities, authenticated-only inference, excluded
internal routes and the public static catalog. Browser tests separately verify
cross-user access and same-origin mutation controls.

## Browser controls with interactive OpenCode

`browser-harness-rehearsal.cjs` coordinates browser actions with a separately
running OpenCode session. Use the same private browser-test directory/environment
as above, including the administrator key and public server certificate. Keep
that directory private; the script saves a one-hour user key there for the harness.

1. Run with `REHEARSAL_ACTION=setup`; launch the harness using
   `$KEY_DIRECTORY/harness-rehearsal.key` and `mock/demo-cheap`.
2. Send a prompt. The synthetic rates must produce at least $0.01 recorded spend.
3. Run with `REHEARSAL_ACTION=deny`; another prompt should show budget denial.
4. Stop OpenCode's retry, run with `REHEARSAL_ACTION=allow`, explicitly select
   `mock/demo-cheap` in `/models`, and send a new prompt.
5. Always run with `REHEARSAL_ACTION=restore`, including after failure. It restores
   global policy, suspends the test profile and deletes its local key copy.

```sh
REHEARSAL_ACTION=setup node tests/pricetag/browser-harness-rehearsal.cjs
```

Run the same command with `deny` and `allow` at their respective steps. Finish
with:

```sh
REHEARSAL_ACTION=restore node tests/pricetag/browser-harness-rehearsal.cjs
```

The current USD-denial response says “token budget exhausted”; OpenCode treats
HTTP 429 as retryable. A retry may resume after changing policy. This is neither
an exact dollar spending cap nor automatic model fallback.

## One-command CLI, API and UI acceptance

The suite runs against the **installed mock gateway**, using service APIs rather
than business SQL. It covers users/reporting relationships, budgets, rates,
discounts, finite personal keys, provider/model activation, scoped dashboards,
quota exceptions, offboarding and the demoted-session regression. It leaves
labelled synthetic accounting records. Do not run it concurrently with load or
provider changes.

Install Node 22+, Chromium's runtime dependencies and the pinned browser tools on
the benchmark host. The test package is separate from the deployed services:

```sh
sudo dnf -y module install nodejs:22/common
sudo dnf install -y nss atk at-spi2-atk cups-libs libdrm libXcomposite \
  libXdamage libXrandr mesa-libgbm pango alsa-lib libxkbcommon
npm ci --ignore-scripts --prefix tests/pricetag/browser
sudo tests/pricetag/browser/node_modules/.bin/playwright install chromium
sudo python3 tests/pricetag/demo-suite \
  --node-modules "$PWD/tests/pricetag/browser/node_modules" \
  --output /root/pricetag-admin/demo-acceptance
```

Use a new output directory for each run. Keys remain on the host in temporary
root-private files; no browser traces or key screenshots are recorded. The
output contains per-test logs and `results.json`.

If the VM cannot reach its own public IPv4 through the cloud firewall, add
`--loopback-public-ip`. This temporarily routes the **configured public IPv4** to
local services and removes the route afterward. TLS hostname verification and
the configured browser Origin remain intact. This verifies the application, not
external firewall reachability. After an interrupted process, inspect/remove the
specific local route before rerunning; never run the option on a real deployment.

The unit regressions are included in the normal SSS offline suite. Full RHEL
browser acceptance is a separate explicit qualification run; it is not claimed
as automatically running in GitHub-hosted CI.

## CLI and public API

`scripts/pricetag/manage` is the root-only private management client.
`scripts/pricetag/api` uses the public HTTPS API with the same key-login and role
checks as the browser. Its session remains in memory. It saves responses to a
new private file because some responses contain a one-time key.

```sh
python3 scripts/pricetag/api GET /api/v1/management/users \
  --url "$GATEWAY_URL" --key-file "$CLIENT_DIR/admin.key" \
  --ca-file "$CLIENT_DIR/ca.pem" --output users.json
```

For mutations, put the JSON payload in an owned mode-0600 file and pass
`--input`. Supported methods are GET, POST, PUT, PATCH and DELETE. Never pass a
key as an argument or retry an uncertain key issuance automatically. Provider
activation returns before completion: poll `/api/v1/management/gateway/status`;
brief read failures are expected while Praxis restarts.

## Capacity and rate limiting

Run separately from functional tests. This mock-only helper varies users and
simultaneous request streams independently, samples RHEL/container/PostgreSQL
resources, reconciles successful requests with the ledger and restores the
original request limiter:

```sh
sudo python3 scripts/pricetag/capacity --rates 30 1000 \
  --cases 1x16 20x1 20x4 20x16 50x8 --requests 30
```

Each `users x streams` case has 30 sequential requests **per stream**. The
synthetic streaming response takes about three seconds. Rejected requests do
not count as successful inference. A higher configured limit is not a capacity
claim. The generator and mock backend consume resources on the same host.

The runner stops on unexpected errors, service restarts or resource thresholds.
It saves the original gateway configuration in the result directory for recovery
after an uncatchable interruption. Keep that directory private: it also contains
test keys. Export only the fixed-schema numeric measurements:

```sh
sudo python3 scripts/pricetag/export-capacity /root/pricetag-admin/capacity-RUN \
  --check
sudo python3 scripts/pricetag/export-capacity /root/pricetag-admin/capacity-RUN \
  > capacity-measurements.json
```

Replace `capacity-RUN` with the result directory printed by the runner. The
exporter excludes keys, subjects, URLs, configuration and raw logs. Transfer this
export for plotting; never transfer the full private result directory.

With matplotlib installed, generate PNG/SVG summaries and resource timelines:

```sh
python3 scripts/pricetag/plot-capacity /path/to/capacity-measurements.json \
  --output /path/to/graphs
```
