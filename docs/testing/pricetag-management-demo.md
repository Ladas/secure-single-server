# Management demo on RHEL

**Candidate workflow — reduced-image deployment qualification pending.** Use a dedicated
benchmark VM and the matching PriceTag management candidate. Published PriceTag
images do not yet contain these management APIs. All inference is synthetic.

## Prepare images

Run on the RHEL VM from this checkout. Set `METERING_SOURCE` to the reviewed
PriceTag candidate source directory. Build or pull matching standalone MaaS and
Praxis images using the [installation guide](../quickstarts/remote-gateway-pricetag/README.md).
Keep these images in root's Podman store. Get their immutable IDs:

```sh
export REPO="$PWD"
sudo podman build -f "$REPO/configs/pricetag/Containerfile.metering" \
  -t localhost/pricetag-metering:management-candidate "$METERING_SOURCE"
sudo podman images --no-trunc
```

## Install the mock gateway

Set the public hostname and three image IDs from the previous step. The installer
imports them into the service account, prepares the Quadlets, starts the services,
and keeps provider configuration host-managed. It refuses existing data. The reduced PriceTag image does not include provider/model editing in the browser.

```sh
sudo "$REPO/scripts/pricetag/install-demo" \
  --hostname "$GATEWAY_HOST" \
  --praxis-image "$PRAXIS_IMAGE_ID" \
  --maas-image "$MAAS_IMAGE_ID" \
  --metering-image "$METERING_IMAGE_ID"
```

Append `--plan` to inspect the steps without changing the host. Installation uses
synthetic credentials only. Keep TCP 8443 restricted to the testing IPs while
qualifying the candidate; database and management ports remain private.

## Prepare the live UI demo

1. Sign in at `https://<gateway-host>:8443/login` using the administrator key at
   `/root/pricetag-admin/admin.key`. Transfer/display keys only in a private terminal.
2. Open **Account management → Model pricing**. Configure illustrative rates for
   upstream IDs `fixture` and `fixture-cheap`; label them synthetic. For example,
   USD/MTok input/output rates of 1,000/2,000 and 100/200 make the mock differences
   visible. Set both cache rates explicitly. These are demo rates, not vendor prices.
3. Create the 20-user, two-team fixture. The script creates finite keys through
   APIs and generates mock usage; it does not write business tables directly.

```sh
cd "$REPO"
sudo python3 tests/pricetag/rhel-demo-fixture.py \
  --output /root/pricetag-admin/demo-team-fixture
```

Use `--resume` with the same arguments after an interrupted fixture run. Private
keys and its progress manifest remain in the output directory. Resume skips
recorded successful traffic; it is not an exactly-once workload after a crash.

Perform live user/team, key, budget and pricing changes in the UI. Prepare provider/model routes before the demo using the host workflow.
Fixture generation and automated assertions may use APIs. Do not use terminal
management as a substitute for a missing demo UI.

## API qualification

Run on an idle mock deployment. The fixture and tests verify the generated mock
configuration before mutations. They do not require a provider-management adapter.

```sh
sudo python3 tests/pricetag/rhel-pricing.py \
  --output /root/pricetag-admin/demo-pricing-checks
sudo python3 tests/pricetag/rhel-quota-matrix.py \
  --output /root/pricetag-admin/demo-quota-checks
```

Use a new output directory each run. The quota test creates synthetic usage,
including a 10B-token safety-gate fixture; exclude these identities from the
presentation. Tests restore policy and suspend their test identities. A global
post-budget exception bypasses the USD gate, not the legacy token gate.

Clean up the presentation fixture when finished (accounting history is retained):

```sh
sudo python3 tests/pricetag/rhel-demo-fixture.py --cleanup \
  --output /root/pricetag-admin/demo-team-fixture
```

Follow the [browser walkthrough](../quickstarts/remote-gateway-pricetag/demo.md)
for the live presentation. Full automated browser deployment coverage is being
prepared in a separate CI PR. Previous larger-image browser results are not
qualification of this reduced demo image.
