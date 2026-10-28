# Walk through the gateway demo

Start with the [quickstart](README.md). Use synthetic providers on a dedicated
host for budget-exhaustion tests; real-provider requests incur charges.
The PriceTag demo image enables the views below. The optional provider editor
is not included.

## 1. Onboard users and a manager

Sign in at `https://<gateway-host>:8443/login` with the administrator key.
Open **Administration → Users** (`/admin`):

1. In **Create or update a login**, create an ordinary user and a second ordinary user to be their
   manager. Keep their login names stable: usage belongs to that identity.
2. In the existing user table, choose the manager in the user’s **Manager**
   dropdown and retain the `user` role. Changes save immediately. A manager does not need administrator privileges.
3. In **Administration → Safety Net → Per-user monthly overrides**, choose the user and set their monthly USD limit.
   **Use global default** removes an override; it does not reset spending.
4. Return to **Users → Issue onboarding key**, select each user and choose a name and finite
   lifetime. This creates an additional key, not a rotation. Use **Copy key** or
   **Download .key**; the secret is never displayed. Keep the downloaded file private
   (`chmod 600 /path/to/pricetag.key`) and pass its path to the client helper. Do not include keys in screenshots or recordings.

Repeat for more users. The UI supports individual creation; the automated
[20-user mock fixture](../../testing/pricetag-management-demo.md) prepares a
larger demonstration through the same APIs, not through a bulk-import UI.

## 2. Generate and observe usage

Follow [Connect OpenCode](README.md#5-prepare-the-local-connection) using the
ordinary user's key. Send requests to the preconfigured expensive and cheaper
model aliases. Provider routes are prepared with the [provider helper](providers.md);
creating a price entry alone does not expose a model.

- **Administrator:** open `/admin`, inspect users, models, tokens and USD spend.
  The usage view shows recorded activity, not every configured model.
- **User:** sign in with their key in a separate browser profile and open
  `/dashboard`. Confirm that only their spending is visible.
- **Manager:** use another profile and open `/manager`. Confirm that the team
  view contains the reporting subtree, not unrelated teams.

Allow time for accounting to arrive. Distinguish discount savings shown by the
UI from measured savings achieved by switching models. Synthetic data does not
prove model quality or a fixed cost reduction.

## 3. Apply controls and continue on an allowed model

1. In **Administration → Safety Net → Per-user monthly overrides**, lower the test user's
   allowance below their recorded spend. Use an ordinary user: admin accounts
   are exempt from this spending gate.
2. Send another paid-model request and observe denial after policy caches refresh.
3. In **Administration → Safety Net**, configure the approved post-budget model
   ID. Use its **billed upstream ID**, not just its gateway alias.
4. Select the corresponding alias explicitly in OpenCode and retry. Confirm the
   exception works and a different paid model remains blocked.
5. Restore the user's allowance and the exception list after the demonstration.

Exceptions are **global**, not per-user automatic fallback routing. A cheap model
can still cost money. The legacy token gate remains independent. Concurrent and
in-flight requests can overshoot the USD allowance; this is not a reserved-funds
hard cap. Use the [mock quota tests](../../testing/pricetag-management-demo.md)
to verify behavior without spending real money.

The picker stores the **billed model ID**. Gateway aliases sharing that ID share
the exception. This exception list is global; it is not a per-user model allowlist.

## 4. Review prices and discounts

- **Administration → Pricing:** inspect imported catalog prices and their units.
- **Administration → Pricing Discounts:** save a scoped discount policy and
  verify its effective rates. Saving the policy refreshes prices.
- **Administration → Pricing Discounts → Model pricing:** the demo image also provides the
  optional custom-rate API/UI. Set input, output, cache-read and cache-write
  rates explicitly in USD per million tokens. Use the billed model ID.

New rates apply to future events. Historical repricing is a separate, deliberate
API operation with a preview and confirmation hash; it is not a UI action.
See [pricing operations](pricing.md) for refresh, catalog and repricing examples.

## 5. Replace keys and offboard

In the user's **My keys** (`/management`), create a replacement key,
download it, update the client's key-file path, test it, then revoke the old key.
Active keys appear first; revoked/expired records are in expandable history.
Expiry dates and countdowns show when a key will stop working. Administrators
can issue onboarding keys, check active-key counts and **Revoke all keys** for a selected user. Disabling a user and revoking
keys are separate controls; test both as described in [user management](users.md).
Do not claim key revocation also terminates every existing browser session.

## What remains a slide or a separate integration

Installation and provider configuration use the documented CLI. A new hosted
inference service needs its own deployment and a configured gateway route;
changing that provider is not part of the reduced browser UI. RHOAI growth,
SSO onboarding, managed databases and Side-Eye are future integrations. No
automatic cheaper-model routing or guaranteed 10× saving is demonstrated here.
