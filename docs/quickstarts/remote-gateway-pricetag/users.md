# Users, budgets and keys

The installer always creates `admin`. Alice and Bob are optional sample users.
Ordinary users inherit the default monthly allowance ($5 unless changed);
individual overrides are optional. MaaS keys expire after at most 90 days.
Use ordinary-user keys for inference: the administrator is quota-exempt.

## Open the management session

From the **workstation shell used for installation**:

```console
ssh -t "${SSH_OPTS[@]}" "$RHEL_HOST" \
  'cd ~/secure-single-server && exec bash'
```

Run management commands below in that SSH session. In a new workstation shell,
first restore the variables from [connection setup](README.md#1-set-the-connection).
Type `exit` when finished to return to your workstation.

## Create a user

```console
sudo python3 scripts/pricetag/user --subject carol --name Carol \
  --monthly-usd 5 --key-lifetime 30d --output /root/pricetag-admin/carol.key
sudo cat /root/pricetag-admin/carol.key
```

The key is saved privately at the requested path. Omit `--monthly-usd` to use
the deployment default. Omit `--key-lifetime` for 90 days. Browser login accepts
the same key, but personal dashboards are pending upstream.

Back on your workstation, follow [Prepare the local connection](README.md#4-prepare-the-local-connection)
with `INFERENCE_USER=carol`. Then launch OpenCode with `--key-file "$CLIENT_DIR/carol.key"`.
Each key belongs to one user; switching key files switches whose budget is charged.

## Change a budget

```console
sudo python3 scripts/pricetag/user --subject carol --monthly-usd 10 --no-key
```

Existing keys and usage are preserved. Allow up to 15 seconds for cached
admission decisions to expire.

## List users and keys

The administrator dashboard's **Users** page lists local identities. To list
one user's keys and expiry/status metadata (not the key values):

```console
sudo python3 scripts/pricetag/maas-key list --subject carol
```

To read a saved key for login or secure copying:

```console
sudo cat /root/pricetag-admin/carol.key
```

## Rotate or revoke a key

```console
sudo python3 scripts/pricetag/user --subject carol --rotate \
  --key-lifetime 30d --output /root/pricetag-admin/carol-next.key
```

Copy the new file to your workstation, then use its path as `KEY_FILE` and
restart OpenCode. Rotation saves the replacement before
revoking previous keys named `inference`; use a new output filename each time.
To revoke a specific key, copy its ID from `list`:

```console
sudo python3 scripts/pricetag/maas-key revoke --subject carol --key-id OLD_KEY_ID
```

<details>
<summary>Copy a rotated key and switch OpenCode</summary>

Run in the **workstation installation shell**, after exiting SSH:

```console
umask 077
KEY_FILE="$CLIENT_DIR/carol-next.key"
ssh "${SSH_OPTS[@]}" "$RHEL_HOST" 'sudo cat /root/pricetag-admin/carol-next.key' > "$KEY_FILE"
chmod 600 "$KEY_FILE"
printf 'User key saved at: %s\n' "$KEY_FILE"
```

In your project shell, set `KEY_FILE` to that printed path and rerun the
[OpenCode command](README.md#5-run-opencode). For a saved native configuration,
regenerate it with this key path. Alternatively, securely replace the contents
of the key file it already references and restart OpenCode.

</details>

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

| Task | Available interface |
| --- | --- |
| View aggregate and user spending | Administrator dashboard |
| View local users and change administrator roles or manager relationships | Administrator **Users** |
| Set the default monthly allowance and post-limit model exceptions | Administrator **Safety Net** (`/api/v1/admin/safety-net`) |
| Create users or change an individual allowance | SSH: `scripts/pricetag/user` |
| Issue, list, rotate or revoke keys | SSH: `scripts/pricetag/maas-key` using the private MaaS API |
| Configure providers, credentials and advertised models | SSH: `scripts/pricetag/providers` |
| View your own spending as an ordinary user | Pending upstream; login currently shows “coming soon” |

The default monthly allowance applies separately to each user. An individual
allowance overrides that default. This deployment starts with an empty
post-limit exception list, so no model bypasses the USD limit.

<details>
<summary>Administration boundaries and upstream API gaps</summary>

MaaS owns keys; metering owns partner identities, usage and budgets. The public
gateway exposes authenticated dashboard routes, not MaaS management or metering
partner credentials. Browser key-management tabs and Kubernetes routing controls
remain unavailable. The Pricing Discounts tab is also not exposed; alias-price
refresh and historical repricing require separate qualification. Use the SSH
commands above for supported management.

The pinned metering revision removed the legacy people, identities and quota
admin APIs. Its partner-user API expects email-based identities and does not
expose individual budget edits. The SSH `user` command uses a small, transactional
PostgreSQL adapter for local subjects and budget overrides, recording changes in
`org_audit`. This adapter is tied to the metering schema and must be tested on
upgrades. It does not call the removed APIs or require Kubernetes.

An initial `admin` partner record receives the `super_admin` role during startup.
Ordinary users retain the `user` role. The built-in `admin` identity is quota-exempt because it has `super_admin`.
Granting that role to another user also exempts their inference from quotas;
distribute ordinary-user keys to clients.

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
