# Management CLI and API

For the management candidate, prefer **Account management** in the browser.
For automation, `scripts/pricetag/manage` calls the private loopback API with the
host's protected service credential. It does not print credentials or response
bodies, and it refuses to overwrite response files.

Provider/model `gateway/*` APIs described below require the optional **full**
management image and adapter. The reduced demo supports users, budgets, prices,
policy and keys; manage providers through the host CLI instead.

## Remote HTTPS client

From a checkout on your workstation, use the same key and CA as browser/harness
access. The helper creates an **in-memory session**, applies normal server-side
role checks, and writes the response to a new private file:

```sh
python3 scripts/pricetag/api GET /api/v1/management/users \
  --url "$GATEWAY_URL" --key-file "$CLIENT_DIR/admin.key" \
  --ca-file "$CLIENT_DIR/ca.pem" --output users.json
```

Use an ordinary user's key with `/me/keys` or scoped dashboard APIs. Personal key
operations cannot manage another user's keys, including when called by an admin.
Supported methods: GET, POST, PUT, PATCH and DELETE. The helper also accepts `/api/v1/pricing?used=0` to list the complete catalog.
Other query strings are rejected; use a direct authenticated API client for filtered reporting.

<details>
<summary>Change a user's budget over HTTPS</summary>

```sh
umask 077
printf '%s\n' '{"subject":"carol","monthly_usd":5}' > budget-input.json
python3 scripts/pricetag/api PUT /api/v1/management/budgets \
  --url "$GATEWAY_URL" --key-file "$CLIENT_DIR/admin.key" \
  --ca-file "$CLIENT_DIR/ca.pem" --input budget-input.json \
  --output budget-result.json
```

Input files must be owned by the caller with mode 0600. Pass provider credentials
only in such a file, never as command arguments. Inspect key-issuance responses
privately; delete credential input files when finished. A transport failure does
not prove that a mutation failed; the helper does not retry it.

</details>

## Host management over SSH

Run from the installed repository **on RHEL**:

```sh
sudo install -d -m 0700 /root/gateway-management
sudo python3 scripts/pricetag/manage GET users \
  --output /root/gateway-management/users.json
sudo python3 scripts/pricetag/manage GET gateway/config \
  --output /root/gateway-management/gateway.json
```

Choose a new output filename for each call. Inspect files privately with
`sudo less`; key-issuance responses contain a one-time key.

## Change a budget

Create a private request file and edit it:

```sh
sudo install -m 0600 /dev/null /root/gateway-management/budget-input.json
sudoedit /root/gateway-management/budget-input.json
```

Enter:

```json
{"subject": "carol", "monthly_usd": 5}
```

Then apply it:

```sh
sudo python3 scripts/pricetag/manage PUT budgets \
  --input /root/gateway-management/budget-input.json \
  --output /root/gateway-management/budget-result.json
```

The same resource names are available for `users`, `prices`, `policy`, `keys`,
`gateway/config`, `gateway/status` and `gateway/discover`. They use the candidate
PriceTag management API schemas. The server validates allowed methods and fields;
this client does not bypass authorization or manipulate database tables.

<details>
<summary>Edit provider/model configuration through the same API as the UI</summary>

Transform the saved configuration into an update request:

```sh
sudo python3 -c 'import json, os; os.umask(0o077); p="/root/gateway-management/"; current=json.load(open(p+"gateway.json")); json.dump({"revision":current["revision"],"configuration":current["configuration"],"credentials":{}},open(p+"gateway-input.json","x"),indent=2)'
sudoedit /root/gateway-management/gateway-input.json
sudo python3 scripts/pricetag/manage PUT gateway/config \
  --input /root/gateway-management/gateway-input.json \
  --output /root/gateway-management/activation.json
sudo python3 scripts/pricetag/manage GET gateway/status \
  --output /root/gateway-management/activation-status.json
```

Edit providers/models inside `configuration`. Supply a new provider credential in
`credentials` under its provider name using the private editor; never put it in
command arguments. Existing credentials need not be resubmitted. Origins must
already be approved by the host administrator.

Activation is asynchronous. Compare the operation IDs in the two response files;
`state: complete` is success, `running` needs another status query with a new output
filename, and `failed` needs inspection. A restart can lose PriceTag's operation
status; reload configuration and verify health instead of blindly retrying.

</details>

**On errors:** inspect server state before repeating a mutation. A transport or
output error does not prove that key issuance or activation failed server-side.
The client retains its private response file for inspection and does not retry.
Remove request files containing provider credentials when no longer needed.
