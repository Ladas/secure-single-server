# Measure the PriceTag gateway on RHEL

Run this on the separate mock-only performance VM after following the
[deployment runbook](aws-pricetag.md). The test measures HTTPS, Praxis,
PriceTag accounting and PostgreSQL with a synthetic LLM. It does not measure
model quality, GPU capacity or real-provider latency.

Each worker uses a distinct non-admin MaaS key and sends one request at a time.
The default phases use 1, 5, 10 and 20 users, with five streamed OpenAI Chat
requests per user and one second between requests. The fixture returns two
input and three output tokens per request. Reports contain timings, statuses
and per-user counts, not prompts, keys or response bodies. Failures are retained
and cause a nonzero exit. Run with new test users so the ledger contains only
the events being reconciled.

## Run the test

On the performance RHEL host:

```console
cd ~/secure-single-server
PERF_RUN="perf-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:8])')"
sudo python3 scripts/pricetag/perf users \
  --tokens "/root/pricetag-admin/$PERF_RUN" --prefix "$PERF_RUN" --count 20 \
  --gateway https://localhost:8443 --ca /etc/praxis-pricetag/ca.pem \
  --admin-key /root/pricetag-admin/admin.key --maas-url http://127.0.0.1:18086
sudo python3 scripts/pricetag/perf run --url https://localhost:8443 \
  --ca /etc/praxis-pricetag/ca.pem --tokens "/root/pricetag-admin/$PERF_RUN" \
  --concurrency 1 5 10 20 --requests 100 --think 0 \
  --output "/root/pricetag-admin/$PERF_RUN.json"
sudo python3 scripts/pricetag/perf verify \
  --report "/root/pricetag-admin/$PERF_RUN.json" \
  --database pricetag-db --service-user praxis-svc
```

Each test identity receives a $100 monthly USD override, so the normal
spending enforcement remains active without stopping the synthetic run. The
edge rate limit remains enabled. This profile sends 3,600 requests across the
four concurrency levels and checks that the ledger records exactly the
expected per-user requests and token counts. Include the single smoke request
when comparing the final ledger total.

## Record resource and storage growth

In a second SSH session, sample the containers while the run is active. Define
`svc` once in that shell:

```console
PRICETAG_UID=$(id -u praxis-svc)
svc() {
  (cd /tmp && sudo -u praxis-svc env \
    XDG_RUNTIME_DIR="/run/user/$PRICETAG_UID" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$PRICETAG_UID/bus" "$@")
}
svc podman stats --no-stream --format json \
  pricetag-gateway pricetag-maas pricetag-metering pricetag-db pricetag-provider
svc podman exec pricetag-db psql -U metering -d metering -At -c \
  "SELECT count(*), pg_total_relation_size('usage_events') FROM usage_events;"
svc podman exec pricetag-db psql -U metering -d metering -At -c \
  'SELECT pg_database_size(current_database());'
free -h
df -h / /var/lib/containers
```

For repeated machine-readable samples, start this while the load command runs
in the first session. Reuse the same value printed in the first session:

```console
PERF_RUN='perf-REPLACE_WITH_RUN_ID'
sudo python3 scripts/pricetag/observe \
  --samples 160 --interval 10 \
  --output "/root/pricetag-admin/$PERF_RUN-observe.jsonl"
```

This collects a little over the expected load duration. Capture repeated
samples and before/after disk use for longer soaks. Include host CPU, memory,
disk, service restarts, PostgreSQL/WAL size and report contents. A single
snapshot does not establish peak usage or sustained capacity. Local laptop runs
are not substitutes for RHEL measurements.

## USD quota probe

Run this only on the mock-only performance host. The probe used one MaaS user
with a $0.01 monthly override and temporarily raised the `fixture` model price
to $75/$450 per million input/output tokens so the quota could be reached with
a small request count. It restored the original fixture price ($0.75/$4.50 per
million) immediately after the probe. Never apply these prices to a real
provider or the real gateway.

Six mock requests accumulated $0.009 against the $0.01 allowance. After the
15-second decision cache expired, a seventh request was admitted, bringing
spend to $0.0105. After a second cache expiry, the eighth request was rejected
with HTTP 429. This confirms the USD gate works but also measures a $0.0005
overage in this serial probe. Faster or concurrent traffic can increase
overage during the cache window; the budget is not an exact billing ceiling.

## Acceptance and cleanup

Require all requests to complete without unexpected 4xx/5xx responses, complete
streams, exact ledger reconciliation, no service restart or out-of-memory kill,
and no unexpected disk growth. Inspect the dashboard and user isolation
separately; this benchmark does not prove dashboard authorization or long-term
retention behavior.

The metering image currently has no configured raw-event retention deletion.
Do not delete rows manually on a test database. Record its growth rate and keep
the test host isolated; define a reviewed retention and backup policy before
using this deployment for long-lived users. The tested rootless Podman units use
the `k8s-file` log driver with no per-container size cap (`-1B`); the short run
showed stable journald usage, but it does not establish a long-term log bound.
Set and verify a log rotation limit before running a long-lived service.
