# PriceTag gateway performance tests

These tests measure the HTTPS/JWT gateway and PriceTag accounting with synthetic
LLMs. They do not measure model quality, GPU capacity or real provider latency.
Use a dedicated test deployment and `perf-*` users; no cloud keys are required.
Keep USD enforcement and the normal public rate limiter enabled.

## Workload and evidence

Each worker has a distinct non-admin JWT and one request in flight. Phases use
1, 5, 10 and 20 workers, with a pause after each request. The default workload
is OpenAI Chat SSE with complete usage and terminal events. The native fixture
reports exactly two input and three output tokens per request. Responses and
Messages protocol correctness is covered separately by the acceptance suite.
The `--json` option runs non-streaming Chat. Each request opens a new TLS
connection; results include handshakes and are not a keepalive-only benchmark.

The report records successes, status counts, throughput and p50/p95/p99
completion latency, plus p95 time to first response byte. This is **not** time
to first model token. Failures are retained, are excluded from successful
latency percentiles, and make the command fail. Run-level elapsed time includes
user pauses. No prompts, tokens or response bodies are written to reports.

Use unique test users for each report. Ledger reconciliation expects their
entire history to belong to that report, across all its phases. It waits for
asynchronous delivery and compares exact per-user request/input/output/total
token counts. A mismatch is a failure even if every HTTP request returned 200.

## Local Podman

Start [the local deployment](pricetag.md#build-the-images-and-test-locally).
Finish correctness tests before provisioning load users: both update the live
registry, and running them concurrently can distort this test.

Configure the private fixture for long-lived streams. The one-second delay is
between SSE events; Chat has three delayed gaps, approximately three seconds
per response. The control endpoint is container loopback only:

```console
podman exec praxis-pricetag-provider python3 -c '
import json, urllib.request
request = urllib.request.Request("http://127.0.0.1:19000/scenario",
    data=json.dumps({"mode":"delayed","delay":1,"reset":True}).encode(),
    headers={"Content-Type":"application/json"})
urllib.request.urlopen(request).read()
'
PERF_RUN="perf-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:8])')"
python3 scripts/pricetag/perf users --local-state .state/pricetag \
  --tokens ".state/pricetag/$PERF_RUN" --prefix "$PERF_RUN" --count 20
python3 scripts/pricetag/perf run --url https://localhost:8443 \
  --ca .state/pricetag/tls/ca.pem --tokens ".state/pricetag/$PERF_RUN" \
  --concurrency 1 5 10 20 --requests 5 --think 1 \
  --output ".state/pricetag/$PERF_RUN.json"
python3 scripts/pricetag/perf verify --report ".state/pricetag/$PERF_RUN.json"
```

This smoke test sends 180 requests. Each test person gets a $100 monthly
allowance, preserving enforcement while avoiding accidental budget exhaustion.
Use new users and a new output file for a longer run, such as 100 requests per
worker. Do not compare a throttled run against an unthrottled one without
reporting the difference. The JSON workload may hit the unchanged 30 RPS edge
limit if pauses are reduced.

In a second terminal, capture resource snapshots while the run is active:

```console
podman stats --no-stream --format json \
  praxis-pricetag-gateway praxis-pricetag-metering praxis-pricetag-db praxis-pricetag-provider
podman exec praxis-pricetag-db psql -U metering -d metering -At -c \
  "SELECT count(*),pg_total_relation_size('usage_events') FROM usage_events;"
podman exec praxis-pricetag-db psql -U metering -d metering -At -c \
  "SELECT pg_database_size(current_database());"
```

Collect before/after disk sizes and periodic resource samples for a soak; one
snapshot does not establish a peak. Record Podman VM CPU/RAM and architecture.
The mock, database and load generator share resources on this setup.

Restore the normal immediate fixture before correctness tests:

```console
podman exec praxis-pricetag-provider python3 -c '
import urllib.request
request = urllib.request.Request("http://127.0.0.1:19000/scenario",
    data=b"{\"mode\":\"ok\",\"reset\":true}", headers={"Content-Type":"application/json"})
urllib.request.urlopen(request).read()
'
```

## Dedicated RHEL gateway

Launch using [aws-pricetag.md](aws-pricetag.md), then install with
`scripts/pricetag/prepare.py --mock-provider`. This uses only the private
`pricetag-private` network and publishes HTTPS 8443. The mock starts with the
same one-second stream delay. Do not run this synthetic capacity test on a
real provider alias or the current GPU pilot.

On RHEL, from the reviewed server checkout:

```console
PERF_RUN="perf-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:8])')"
sudo python3 scripts/pricetag/perf users --tokens "/root/pricetag-admin/$PERF_RUN" \
  --prefix "$PERF_RUN" --count 20
sudo python3 scripts/pricetag/perf run --url https://localhost:8443 \
  --ca /etc/praxis-pricetag/ca.pem --tokens "/root/pricetag-admin/$PERF_RUN" \
  --concurrency 1 5 10 20 --requests 5 --think 1 \
  --output "/root/pricetag-admin/$PERF_RUN.json"
sudo python3 scripts/pricetag/perf verify --report "/root/pricetag-admin/$PERF_RUN.json" \
  --database pricetag-db --service-user praxis-svc
```

Use the deployment guide's `svc` function for `podman stats` and SQL queries,
substituting container names `pricetag-gateway`, `pricetag-metering`,
`pricetag-db`, `pricetag-provider`. Record host `free -h`, disk free space,
service restarts and CPU/IO utilization alongside results. Raw usage queries
and dashboard polling can compete with ingestion as history grows; repeat
against a representative test history before claiming sustained capacity.

For a client-network measurement, securely copy only the test users' JWT files
and CA to a private client directory, run the same driver with the public HTTPS
origin, then copy the non-secret report back for ledger reconciliation. The
AWS `/32` rule must permit that client. Do not mix local and remote load into
one report. SSH-loopback and remote-client results measure different paths.

## Acceptance and cleanup

For the initial 20-user smoke test require no unexpected 4xx/5xx, complete
streams, exact ledger counts, no service restart/OOM, and no loss of dashboard
access during load. Establish application latency objectives from the first
measured baseline; this procedure does not invent an unmeasured SLA. Follow
with a longer soak and a separate client generator before accepting capacity.

Revoke each test subject with `scripts/pricetag/credentials revoke`; keep its
ledger for review. Do not delete usage to make reconciliation pass. Protect
private token directories and retain redacted reports, image IDs and machine
settings. A mock-only Quadlet deployment still needs RHEL qualification on the
new VM; local tests alone do not establish its operating-system behavior.
