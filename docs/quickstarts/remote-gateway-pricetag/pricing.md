# Price operations

Run on RHEL in `~/secure-single-server`. Provider discovery returns model IDs,
not prices. Use verified USD-per-million rates for your upstream contract.
[Pricing behavior and model refresh](providers.md#3-check-pricing-in-pricetag).

## Recover a first install with missing prices

If startup reports `Missing reviewed price`, the bootstrap transaction rolls
back and the gateway is not started. PostgreSQL, MaaS and PriceTag remain
available for repair. Keep the prepared files, volume and keys; the guided
installer deliberately refuses to overwrite them.

1. Read the private installer log and the alias-to-source mapping:

   ```console
   sudo cat /etc/praxis-pricetag/price-sources.json
   ```

2. Use **Inspect rates or add a missing source price** below to insert verified
   rates for each missing upstream ID. Do not invent a price or use zero for an
   unknown rate. If rates are unavailable, leave the installation stopped.
3. Resume the prepared installation:

   ```console
   cd ~/secure-single-server
   sudo scripts/pricetag/start
   ```

Startup retries the transaction and creates aliases only when all source prices
exist. It reuses the administrator key and prepared user selection. Then return
to [dashboard and client setup](README.md#4-open-the-dashboards).

## Inspect and edit rates

<details>
<summary>Inspect rates over SSH or add a missing source price</summary>

Define this function in the **RHEL management session**:

```console
PRICETAG_UID=$(id -u praxis-svc)
ptsql() {
  (cd /tmp && sudo -u praxis-svc env \
    XDG_RUNTIME_DIR="/run/user/$PRICETAG_UID" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$PRICETAG_UID/bus" \
    podman exec -i pricetag-db psql -X -U metering -d metering -v ON_ERROR_STOP=1 "$@")
}
ptsql -c "SELECT model, input_cost_per_mtok, output_cost_per_mtok, cache_write_cost_per_mtok, cache_read_cost_per_mtok FROM model_pricing WHERE model IN ('gpt-6-luna', 'external/gpt-6-luna');"
```

For a **missing source price**, create a SQL file:

```console
vi /tmp/pricetag-new-price.sql
```

Paste this template, replacing the model ID and all four rate placeholders with
verified **USD per million tokens** (not per-token prices):

```sql
INSERT INTO model_pricing
  (model, provider, input_cost_per_mtok, output_cost_per_mtok,
   cache_write_cost_per_mtok, cache_read_cost_per_mtok)
VALUES
  ('UPSTREAM_MODEL_ID', 'external', INPUT_RATE, OUTPUT_RATE,
   CACHE_WRITE_RATE, CACHE_READ_RATE)
RETURNING model, input_cost_per_mtok, output_cost_per_mtok,
          cache_write_cost_per_mtok, cache_read_cost_per_mtok;
```

Review and apply before model refresh:

```console
cat /tmp/pricetag-new-price.sql
ptsql < /tmp/pricetag-new-price.sql
```

This inserts a source row and refuses an existing ID. Do not substitute zero
for an unknown rate. Startup/pricing refresh can reseed catalog source rates;
new gateway aliases retain the snapshot copied at activation. Changing existing
alias rates or repricing historical usage needs a separate reviewed procedure.

</details>

<details>
<summary>Change a price before a model has recorded usage</summary>

Use the `ptsql` function above. Edit a SQL file with the exact pricing ID and
verified USD-per-million rates. Use an upstream ID **before** alias creation,
or `external/MODEL_ID` for an already-created alias with no usage:

```console
vi /tmp/pricetag-change-price.sql
```

```sql
BEGIN;
LOCK TABLE usage_events IN SHARE MODE;
DO $guard$
BEGIN
  IF EXISTS (SELECT 1 FROM usage_events WHERE model = 'PRICING_MODEL_ID') THEN
    RAISE EXCEPTION 'Model has usage; changing its rate needs a repricing review';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM model_pricing WHERE model = 'PRICING_MODEL_ID') THEN
    RAISE EXCEPTION 'Price row missing; insert it first';
  END IF;
END;
$guard$;
UPDATE model_pricing
SET input_cost_per_mtok = INPUT_RATE,
    output_cost_per_mtok = OUTPUT_RATE,
    cache_write_cost_per_mtok = CACHE_WRITE_RATE,
    cache_read_cost_per_mtok = CACHE_READ_RATE
WHERE model = 'PRICING_MODEL_ID'
RETURNING model, input_cost_per_mtok, output_cost_per_mtok,
          cache_write_cost_per_mtok, cache_read_cost_per_mtok;
COMMIT;
```

Replace both occurrences of the ID in the checks and the ID in the update,
plus all four rate placeholders. Then:

```console
cat /tmp/pricetag-change-price.sql
ptsql < /tmp/pricetag-change-price.sql
```

The transaction briefly blocks event inserts while checking for usage. It
refuses to reprice a used model. Editing a source row does **not** update existing
alias rows; inspect the exact alias charged by clients. Allow cached budget
checks about 15 seconds to expire. List-price columns shown as savings remain
separate from these actual charging rates.

</details>
