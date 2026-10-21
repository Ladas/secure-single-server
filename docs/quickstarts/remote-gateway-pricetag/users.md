# Users, budgets and keys

Run over SSH from `~/secure-single-server`. The installer creates `admin`,
`alice` and `bob`; Alice and Bob get $5/month by default. Keys are opaque MaaS
API keys, with a maximum lifetime of 90 days.

## Create a user

```console
cd ~/secure-single-server
sudo python3 scripts/pricetag/user --subject carol --name Carol \
  --monthly-usd 5 --key-lifetime 30d --output /root/pricetag-admin/carol.key
sudo cat /root/pricetag-admin/carol.key
```

Use this key for inference and personal dashboard login.
[Local client setup](README.md#4-connect-local-opencode)

## Change a budget

```console
sudo python3 scripts/pricetag/user --subject carol --monthly-usd 10 --no-key
```

Existing keys and usage are preserved.

## List, rotate or revoke keys

```console
sudo python3 scripts/pricetag/maas-key list --subject carol
sudo python3 scripts/pricetag/user --subject carol --rotate \
  --key-lifetime 30d --output /root/pricetag-admin/carol-next.key
```

Update the harness with the new key. Rotation saves the replacement before
revoking previous keys named `inference`; use a new output filename each time.
To revoke a specific key, copy its ID from `list`:

```console
sudo python3 scripts/pricetag/maas-key revoke --subject carol --key-id OLD_KEY_ID
```

<details>
<summary>Rotate with an overlap while clients switch</summary>

```console
sudo python3 scripts/pricetag/maas-key create --subject carol \
  --name laptop-next --expires-in 30d --output /root/pricetag-admin/carol-laptop.key
```

Switch the client, verify inference, then revoke the old key by ID.

</details>

<details>
<summary>Find saved keys or recover access</summary>

```console
sudo find /root/pricetag-admin -maxdepth 1 -type f -name '*.key' -print
```

Saved files may contain revoked keys; `maas-key list` is authoritative. Use
`--admin` for key operations on the configured administrator identity.
An SSH administrator can issue a replacement after all a user's keys expire.
If rotation reports a revocation failure, retain the new file and revoke the
reported old IDs after checking their status.

</details>

## Dashboard or CLI?

| Task | Dashboard | CLI/API |
| --- | --- | --- |
| View personal spend and quota | Personal dashboard | PriceTag personal APIs |
| View spending, edit people and monthly budgets | Admin dashboard | PriceTag admin APIs; `user --no-key` for a user budget |
| Create/link users | Use SSH; UI group picker is unavailable | `user` |
| Issue, list, rotate, revoke keys | Key tabs unavailable | `maas-key` |
| Set provider URLs/credentials | Unavailable | `providers` |

<details>
<summary>API details and UI integration gaps</summary>

### API reference

CLI/API operations are the administrative superset; no browser action is
required for initial providers, identities, monthly overrides or key lifecycle.
The scripts authenticate and call these APIs rather than modifying database rows:

| Operation | CLI or API | Browser |
| --- | --- | --- |
| Provider endpoints, upstream keys, catalog | `scripts/pricetag/providers` | Not configured |
| Create/link a user | `scripts/pricetag/user` → PriceTag people and identities APIs | Add user form is blocked by the empty group picker |
| Set a user's monthly USD allowance | `user --no-key --monthly-usd` → quota overrides API | Admin Quotas |
| Read/edit person details | PriceTag `/api/v1/admin/people` and `/api/v1/admin/people/{slug}` | Admin People |
| Read identities / link an identity | PriceTag `/api/v1/admin/identities` | Admin identity views |
| Read/edit monthly quota policy | PriceTag `/api/v1/admin/quota/policy` | Admin Quotas |
| Issue/list/rotate/revoke keys | `scripts/pricetag/maas-key` → private MaaS API | Not configured |
| Read own usage and allowance | PriceTag `/api/v1/me/quota` and personal dashboard APIs | Personal dashboard |

The table identifies API surfaces, not interchangeable request schemas. For
custom automation, follow the pinned metering handlers and the tested calls in
`scripts/pricetag/user` and `tests/pricetag/rhel-acceptance.py`. PriceTag admin APIs
require an administrator session obtained through HTTPS `/login`, the deployment
CA, and the matching Origin header on mutations. Keep session cookies private;
never send a MaaS trusted-identity header to the public gateway as authentication.
MaaS key operations remain on host loopback through the SSH scripts.

Enabling the existing key-management tabs requires a reviewed adapter for MaaS
ownership, roles, expiry and revocation; exposing their routes alone is not
sufficient. A separate small UI would need the same authorization and session
protections. This deployment deliberately leaves those routes unavailable.

</details>

## Limits

- Monthly admission decisions are cached for about 15 seconds; concurrent or
  delayed requests can overshoot a USD allowance.
- Key revocation stops new key validation, but does **not** end an existing
  dashboard session. It is not complete account offboarding.
- MaaS administration stays on host loopback over SSH. Host administrators and
  configured service peers are privileged.
- Raw-event retention, upgrades and backup/recovery are not qualified by this
  fresh-install guide. Use the [mock benchmark](../../testing/pricetag-perf.md)
  to measure resource and storage growth.
