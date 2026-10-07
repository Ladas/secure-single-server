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

## Longer RHEL run and storage measurements

Use the dedicated mock VM only. The following runs a 20-user smoke phase first,
then 300 requests per user at concurrency 20: 6,000 SSE requests, approximately
20 minutes with the default three-second stream plus one-second pause. Actual
elapsed time is measured. Each report uses fresh users for exact reconciliation.

Before starting, verify that `/etc/praxis-pricetag/models.json` contains only
`demo-model` and that `pricetag-provider.service` is active. No real provider
secrets should be mounted. Keep at least 30% disk free. On RHEL:

```console
cd ~/secure-single-server-pricetag
sudo python3 - <<'PY'
import json
from pathlib import Path
models = json.loads(Path('/etc/praxis-pricetag/models.json').read_text())
assert len(models) == 1 and models[0]['id'] == 'demo-model'
assert Path('/etc/praxis-pricetag/quadlets/pricetag-provider.container').is_file()
print('Mock-only deployment confirmed')
PY
PERF_RUN="perf-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:8])')"
PERF_DIR="/root/pricetag-admin/$PERF_RUN"
sudo install -d -m 0700 "$PERF_DIR"
sudo python3 scripts/pricetag/observe --output "$PERF_DIR/before.jsonl"
```

Stop if the guard or baseline fails. Run the smoke test from the previous
section, using a different prefix/directory. Only after its HTTP and ledger
checks pass, create fresh users for the longer run:

```console
sudo python3 scripts/pricetag/perf users --tokens "$PERF_DIR/tokens" \
  --prefix "$PERF_RUN" --count 20
```

In a second SSH terminal, set `PERF_DIR` to the exact directory printed by
`printf '%s\n' "$PERF_DIR"` in the first terminal, then capture periodic samples:

```console
cd ~/secure-single-server-pricetag
PERF_DIR='/root/pricetag-admin/REPLACE_WITH_PERF_RUN'
sudo python3 scripts/pricetag/observe --samples 60 --interval 30 \
  --output "$PERF_DIR/resources.jsonl"
```

The observer is read-only and writes private JSONL. It records available RAM
and cache separately, pressure, container CPU/memory/block I/O, service restarts,
PostgreSQL size, event count, table/index sizes and dead tuples, WAL counters and
WAL directory size, replication-slot retention, database settings, container
storage and journal usage. Samples themselves add some monitoring load.
If it reports low disk space or a sampling error, stop the load and investigate;
the observer does not terminate a separately launched load process automatically.

In the first SSH terminal:

```console
sudo python3 scripts/pricetag/perf run --url https://localhost:8443 \
  --ca /etc/praxis-pricetag/ca.pem --tokens "$PERF_DIR/tokens" \
  --concurrency 20 --requests 300 --think 1 --timeout 30 \
  --output "$PERF_DIR/load.json"
sudo python3 scripts/pricetag/perf verify --report "$PERF_DIR/load.json" \
  --database pricetag-db --service-user praxis-svc
sudo python3 scripts/pricetag/observe --output "$PERF_DIR/after.jsonl"
```

Keep the HTTP report even if the run fails and still reconcile its successful
requests. Do not restart the same workload with the same users/report. Capture
another snapshot after five idle minutes to distinguish retained data from
transient memory/WAL pressure. Stop the periodic observer with Ctrl-C if it is
still running after that cooldown.

Compare baseline, peak and final samples. Report bytes per additional event for
the ledger **including indexes**, total database growth and WAL separately;
WAL bytes written are cumulative traffic, not retained disk bytes. Also inspect
rollup/audit tables, container layers, journals and build caches. PostgreSQL
file allocation may grow in steps. Increasing filesystem page cache alone is
not a leak: use `MemAvailable`, pressure and container RSS alongside it. The
mock fixture retains request records in memory, and the load generator retains
per-request samples; both are test overhead rather than production gateway
storage. No service restart/OOM, exact ledger totals and bounded resource growth
are required before calling the run successful.

### Current retention policy and gaps

| Storage | Current behavior | Operator action |
| --- | --- | --- |
| `usage_events`, hourly rollups, audit and quota records | Pinned metering has no automatic usage-retention deletion job. Rollup maintenance defaults to 300 seconds; raw ledger is retained and used by enforcement | Size for accumulated history; define an archival/retention policy before continuous operation |
| PostgreSQL dead tuples | Autovacuum settings come from the PostgreSQL image; inspect them in observer output | Track dead tuples and vacuum/analyze activity; vacuum does not expire usage records |
| PostgreSQL WAL | Checkpoints recycle eligible segments; slots/archiving can retain more. `max_wal_size` is not a hard filesystem cap | Compare WAL directory size with settings and slot lag; do not manually remove WAL |
| Database volume | Persists across container restarts; root disk is deleted on VM termination | Keep verified encrypted backups off the instance; this guide does not schedule them |
| Container and system logs | No explicit deployment-specific byte/time retention policy is installed | Inspect actual log driver and journald limits; set/review host limits before long-lived use |
| Image/build cache | Native builds occupy both the operator's Podman storage and loaded service-account images | Inventory both stores after builds; remove only reviewed unused artifacts, never the database volume |
| Test reports, mock records and test users | No automatic cleanup | Retain evidence, revoke test JWTs, and archive reports according to your policy |

Do not add `DELETE` jobs for raw usage as a quick disk fix: current enforcement
and history queries still depend on that ledger, and rollup parity compares
against raw records. Designing safe archival/deletion and changing dashboard
read paths needs separate qualification. This run measures short-term growth;
it cannot establish a monthly retention capacity or certify a production SLA.
