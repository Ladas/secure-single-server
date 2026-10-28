# Mock gateway demo checks

The [demo deployment workflow](../../.github/workflows/pricetag-demo.yml) runs on
a disposable GitHub-hosted Linux runner. It builds the pinned MaaS and PriceTag
demo sources, starts PostgreSQL and Praxis, and runs the API/browser/quota suite
against synthetic inference. No provider keys, SSH credentials or publishing
secrets are required.

This change depends on [management demo #91](https://github.com/redhat-et/secure-single-server/pull/91)
and [image publication #92](https://github.com/redhat-et/secure-single-server/pull/92)
merging first. Source builds use the same reviewed revisions as publication;
replacing them with qualified registry digests is a later optimization.

The build also runs PriceTag’s Go tests against a disposable PostgreSQL instance
with the full migration chain, plus the shared key-control JavaScript tests.

## Coverage

| Area | Assertions |
| --- | --- |
| Public boundary | Private management endpoints remain unavailable; forwarded identity headers do not grant privileges. |
| Users and teams | UI onboarding, manager reassignment, personal/team isolation, 20-user fixture. |
| Keys | Duplicate submission prevention, hidden copy/download, multiple working keys, cross-key usage, expiry countdowns, active/history pagination, owner-only revocation, admin revoke-all and demotion regression. |
| Offboarding and sessions | Suspended account denial, same-origin view-as/logout confirmation, impersonation restrictions. |
| Pricing | Catalog reads, discount save/refresh, custom rates, unchanged historical charges and explicit repricing confirmation. |
| Budgets | Searchable per-user overrides, removal/inheritance, manager monthly totals, configured-model selection, paid-model denial, global exceptions and independent legacy token gate. |

Provider/model editing through a host adapter is excluded. It belongs to the
optional follow-up image and is not required by this suite. Browser tests verify
the actual mock configuration before performing mutations.

## Run on the benchmark RHEL deployment

Install the [mock demo](pricetag-management-demo.md), then install the pinned
browser dependency once from the repository:

```sh
npm ci --prefix tests/pricetag/browser --ignore-scripts
sudo tests/pricetag/browser/node_modules/.bin/playwright install chromium
```

Playwright also needs its OS browser libraries; use a prepared benchmark host.
Then run the suite, using a new private output directory each time:

```sh
sudo python3 tests/pricetag/demo-suite \
  --node-modules "$PWD/tests/pricetag/browser/node_modules" \
  --output /root/pricetag-admin/demo-acceptance
```

If the host cannot reach its own configured public IPv4, append
`--loopback-public-ip`. This temporarily adds a local route for that address and
removes it afterward; it does not change the AWS security group or skip TLS.

## Run the disposable container deployment

Use a disposable Linux host with rootful Podman, Python/PyYAML, OpenSSL, Node and
Playwright. This runner refuses an existing deployment. Pull/build application
images first and set the three image variables to reviewed references:

```sh
sudo python3 tests/pricetag/container-demo.py \
  --maas-image "$MAAS_IMAGE" --metering-image "$METERING_IMAGE" \
  --praxis-image "$PRAXIS_IMAGE" \
  --node-modules "$PWD/tests/pricetag/browser/node_modules" \
  --output /var/tmp/pricetag-demo-acceptance
```

Containers and generated deployment credentials are removed afterward. Ports
are bound to loopback. Private diagnostic logs stay in the output directory;
CI uploads **only structured pass/fail results**, never keys, browser traces or
raw service logs.

Container CI validates application behavior and generated gateway configuration.
It does **not** validate RHEL Quadlets, SELinux or fresh-host installation. Keep
[benchmark RHEL qualification](pricetag-management-demo.md) as a separate check.
