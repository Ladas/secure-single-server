# Manage pricing

Use **Administration → Pricing Discounts** for imported-model discounts. The
pricing view lists rates; historical repricing is an administrator API operation.
These are existing PriceTag capabilities. The candidate fixes discount policy
persistence and preserves recorded charges when future rates change.

| Operation | UI / API |
| --- | --- |
| List all rates, including unused models | Pricing view; `GET /api/v1/pricing?used=0` |
| Read/change imported discounts | Pricing Discounts; `GET/PUT /api/v1/admin/pricing-discounts` |
| Refresh imported prices | Discount save triggers refresh; `POST /api/v1/admin/pricing/refresh` |
| Preview/confirm historical repricing | API only: `POST /api/v1/admin/pricing/reprice` |
| Read repricing status | `GET /api/v1/admin/pricing/reprice/OPERATION_ID` |
| **Optional:** add arbitrary custom rates | Candidate Model pricing UI/API; see below |

## Catalog and discounts

PriceTag fetches selected prices from LiteLLM, falls back to a catalog embedded
in the image, and includes selected local-model rates in its source. The bundled
JSON is **not a runtime-editable configuration file**. Catalog refresh, policy
updates and repricing do not require direct database access.

- A multiplier of `0.8` means 20% off. Use reviewed contract terms.
- Policy save and rate refresh are separate operations. If refresh fails, fix it
  before relying on the new rates. Inspect the response `error` field as well as HTTP status.
- Imported discounts do not automatically modify arbitrary custom rates.
- Existing event-time charges remain unchanged by ordinary updates. An explicit
  historical correction is a separate action; production legacy migrations need
  additional qualification.

## CLI from the installation shell

Use the connection variables from the quickstart and a private administrator key
file. The client logs in over verified HTTPS with an in-memory session. Output
files must not already exist.

```sh
pricing_api() {
  python3 "$REPO/scripts/pricetag/api" "$@" \
    --url "$GATEWAY_URL" --key-file "$CLIENT_DIR/admin.key" \
    --ca-file "$CLIENT_DIR/ca.pem"
}
pricing_api GET '/api/v1/pricing?used=0' --output prices.json
pricing_api GET /api/v1/admin/pricing-discounts --output discounts.json
```

Review/edit `discounts.json`, preserving its `version` and `rules` structure;
then apply and refresh:

```sh
pricing_api PUT /api/v1/admin/pricing-discounts \
  --input discounts.json --output discount-save.json
pricing_api POST /api/v1/admin/pricing/refresh --output price-refresh.json
```

The helper creates private files. Do not paste provider or user keys into request
JSON, URLs or command arguments. See [management authentication](management-api.md).

<details>
<summary>Historical repricing — preview before confirmation</summary>

Create a private request file containing a **specific model and bounded UTC
interval**, the current discount `policy_version`, and `confirm: false`. For example:

```json
{
  "model": "UPSTREAM_MODEL_ID",
  "from": "YYYY-MM-DDT00:00:00Z",
  "until": "YYYY-MM-DDT01:00:00Z",
  "policy_version": "CURRENT_POLICY_VERSION",
  "confirm": false
}
```

Use actual values; this is a schema example. Save as `reprice-input.json` with
mode 0600, then preview:

```sh
pricing_api POST /api/v1/admin/pricing/reprice \
  --input reprice-input.json --output reprice-preview.json
```

Review the row count and old/new totals. To apply, make another private request
with the **same scope**, `confirm: true`, and the returned `operation_id` and
`policy_hash`. Submit it with a new output filename. Query
`/api/v1/admin/pricing/reprice/OPERATION_ID` to inspect status. A changed price
snapshot requires a new preview. This modifies historical charges and rollups;
it is not part of routine future-price maintenance.

</details>

## Optional custom model rates

The candidate's **Account management → Model pricing** and
`PUT /api/v1/management/prices` add/change arbitrary rates or copy a source rate.
This is an optional extension, not an existing upstream capability. The prepared
demo image still includes it; current custom-price bootstrap paths depend on it.

Supply all four USD-per-million-token rates: input, output, cache read and cache
write. Use zero only deliberately. A copied source rate is a snapshot; later
source refreshes do not synchronize it automatically.

**Use the recorded upstream model ID.** Praxis rewrites public aliases before
metering; adding an alias-only price does not price the rewritten event. Adding a
price does not publish a gateway route. Configure models with the
[provider helper](providers.md).

## Missing-price fallback

Missing prices do not block startup. Current estimates per million tokens are
input **$15**, output **$75**, cache read **$0.50**, cache write **$18.75**. These are
fallback estimates, not guaranteed ceilings. A deliberate zero rate differs from
a missing record. Verify new usage after adding or refreshing a rate.
