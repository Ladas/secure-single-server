# Manage pricing

Sign in at `/login` with the administrator key, then open **Admin → Pricing
Discounts**. The Pricing view shows current rates. The upstream discount editor
and pricing APIs are exposed, with the following known limitation.

**Pinned upstream bug:** saving a discount policy returns HTTP 400
(`pricing_discount_policy_rules_check`). The API writes a JSON object while its
database constraint requires an array. Viewing the policy, refreshing the
catalog through the API, and historical-repricing previews work. This deployment
does not patch the upstream schema; do not rely on the editor saving changes.

| Operation | Supported interface |
| --- | --- |
| Inspect rates | Pricing view; `GET /api/v1/pricing` |
| Read/change discount rules | Pricing Discounts; `GET` works, `PUT` has the bug above |
| Refresh source catalog prices | API: `POST /api/v1/admin/pricing/refresh` |
| Preview/correct historical charges | API only: `POST /api/v1/admin/pricing/reprice`; operation status via `GET /api/v1/admin/pricing/reprice/ID` |
| Add an arbitrary missing model price | No upstream editor/API; SSH fallback below |

Management endpoints require a PriceTag super-admin browser session. Our initial
`admin` user has that role. Ordinary inference keys do not grant administration;
log in to obtain the session rather than passing a Bearer key to these APIs.

## What a pricing change affects

- Discounts apply to source catalog rates loaded from LiteLLM. For example,
  multiplier `0.8` means 20% off. Verify the policy against your provider contract;
  upstream includes default commercial discounts that may not apply to you.
- Existing gateway aliases retain the price snapshot copied when they were
  enabled. Refreshing source rates does **not** update those alias rows. Inspect
  the exact `openai/MODEL_ID` or `external/MODEL_ID` charged by the gateway.
- Historical repricing uses existing effective rates; it does not set a new rate
  or synchronize aliases. Dry-run first, review the totals, then confirm using
  the returned operation ID and pricing hash. It changes stored costs and rollups.
- Changing an existing rate can also affect historical totals and budget checks
  that calculate costs from current rates. Do not assume history is immutable
  just because you have not run the repricing API.

See [provider selection and alias pricing](providers.md#3-check-pricing-in-pricetag).
The SQL fallback is only for missing price rows; a general alias-rate editor
with history-preserving changes remains an integration gap.

<details>
<summary>API examples using the signed-in admin browser session</summary>

On the gateway's admin page, open the browser developer console. These requests
use the existing session cookie; no key is pasted into code or a URL.

```javascript
async function pricingAPI(path, method = "GET", body) {
  const response = await fetch(path, {
    method, credentials: "same-origin", redirect: "error",
    headers: {"Content-Type": "application/json"},
    ...(body === undefined ? {} : {body: JSON.stringify(body)})
  });
  if (!response.ok) throw new Error(await response.text());
  const result = await response.json();
  if (result.error) throw new Error(result.error);
  return result;
}
const policy = await pricingAPI("/api/v1/admin/pricing-discounts");
console.log(policy);
```

The UI sends `{version, rules}` with `PUT` to the same endpoint; saving currently
fails with the upstream bug above. To refresh source prices independently:

```javascript
console.log(await pricingAPI("/api/v1/admin/pricing/refresh", "POST", {}));
```

For historical correction, set an exact alias and a bounded UTC interval:

```javascript
const scope = {
  model: "external/MODEL_ID",
  from: "YYYY-MM-DDT00:00:00Z",
  until: "YYYY-MM-DDT01:00:00Z",
  policy_version: policy.version,
  confirm: false
};
const preview = await pricingAPI("/api/v1/admin/pricing/reprice", "POST", scope);
console.log(preview);
```

This creates a durable preview, not a cost update. Review `old_total_usd`,
`new_total_usd` and the scope. Applying a correction is a separate operation:

```javascript
// Run only after approving the preview; this changes historical charges.
console.log(await pricingAPI("/api/v1/admin/pricing/reprice", "POST", {
  ...scope, confirm: true,
  operation_id: preview.operation_id, policy_hash: preview.policy_hash
}));
console.log(await pricingAPI("/api/v1/admin/pricing/reprice/" + preview.operation_id));
```

Changed pricing requires a new preview. Keep the operation ID for status and
resume; the upstream implementation processes bounded transactions and audits
them. Qualify historical correction on a test deployment before production use.

</details>

## Missing prices

Installation continues when a configured model has no source price. Bootstrap
logs a warning and leaves the alias unpriced; PriceTag estimates usage with
these fallback rates in USD per million tokens:

| Input | Output | Cache read | Cache write |
| --- | --- | --- | --- |
| $15 | $75 | $0.50 | $18.75 |

These are upstream estimates, not verified provider rates or guaranteed cost
ceilings. The dashboard remains available after startup. Refresh the source
catalog if appropriate, but note that a source refresh alone does not create a
missing gateway alias price. Inspect the exact alias before assuming it is priced.
A configured zero rate is different from a missing row and does not use fallback.

There is no qualified missing-price alert in this integration. Adding arbitrary
source or alias rates still requires the SSH fallback below. Model refresh via
`providers --refresh-models` continues to require source prices for new aliases.

## SSH fallback: add a missing price

<details>
<summary>Inspect rates over SSH or add a missing price</summary>

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

For a **missing price row**, create a SQL file:

```console
vi /tmp/pricetag-new-price.sql
```

Paste this template, replacing `PRICING_MODEL_ID` with the exact gateway alias (for example,
`external/MODEL_ID`) and all four rate placeholders with
verified **USD per million tokens** (not per-token prices):

```sql
INSERT INTO model_pricing
  (model, provider, input_cost_per_mtok, output_cost_per_mtok,
   cache_write_cost_per_mtok, cache_read_cost_per_mtok)
VALUES
  ('PRICING_MODEL_ID', 'external', INPUT_RATE, OUTPUT_RATE,
   CACHE_WRITE_RATE, CACHE_READ_RATE)
RETURNING model, input_cost_per_mtok, output_cost_per_mtok,
          cache_write_cost_per_mtok, cache_read_cost_per_mtok;
```

For a source row needed by model refresh, use the upstream ID without the
gateway prefix instead. Source and alias rows are distinct. Review and apply:

```console
cat /tmp/pricetag-new-price.sql
ptsql < /tmp/pricetag-new-price.sql
```

This inserts one price row and refuses an existing ID. Do not substitute zero
for an unknown rate. Startup/pricing refresh can reseed catalog source rates;
new gateway aliases retain the snapshot copied at activation. Changing existing
alias rates or repricing historical usage needs a separate reviewed procedure.

</details>
