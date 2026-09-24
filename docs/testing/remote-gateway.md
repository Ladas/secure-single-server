# Remote gateway: private-CA VM tests

Use a full Fedora or RHEL VM. This guide prepares test TLS material and checks
the network boundary; it does not disable TLS verification or install a
system-wide CA. Run workstation commands from the reviewed checkout in Bash.

## 1. Create test TLS material on the workstation

Enter the hostname or IP reachable from your Mac, without a scheme or port.
The certificate SAN must match that value. The VM must retain this address
for the test; recreate the certificate if its address changes.

```console
read -r -p 'Gateway VM DNS name or IP: ' GATEWAY_NAME
install -d -m 0700 .state
LAB_DIR="$(mktemp -d "$PWD/.state/remote-lab.XXXXXX")"
scripts/remote-gateway/credentials lab-tls \
  --directory "$LAB_DIR/tls" --hostname "$GATEWAY_NAME"
printf 'TLS certificate: %s\nTLS key: %s\nNew issuer directory: %s\nPublic test CA: %s\n' \
  "$LAB_DIR/tls/server.pem" "$LAB_DIR/tls/server-key.pem" \
  "$LAB_DIR/issuer" "$LAB_DIR/tls/ca.pem"
```

Follow the [remote installation](../quickstarts/remote-gateway/install.md).
Use the printed paths at its prompts. Only the server TLS key/certificate
and JWT **public** key go to the server. Keep `ca-key.pem` and the JWT private
key on the workstation. The helper refuses overwrites.

On Fedora, include `--development-fedora` in installer commands. Start with
dummy provider secrets if only validating TLS/lifecycle. For real harnesses,
replace them with dedicated provider secrets through the normal workflow.

## 2. Restrict ingress in the guest

On a disposable guest using firewalld, inspect the active interface's zone:

```console
sudo firewall-cmd --get-active-zones
sudo firewall-cmd --list-all
```

Enter that zone and the client's IPv4 `/32` **as seen by the VM**. With NAT,
this may be a VM-network address rather than your Internet-facing address.

```console
{
  read -r -p 'Active firewalld zone: ' FIREWALL_ZONE
  read -r -p 'Approved client IPv4/32: ' CLIENT_CIDR
}
```

Review existing rules first. The zone must not already allow arbitrary 8443
access or have target `ACCEPT`; an additional narrow rule cannot cancel a
broader allow. Keep existing SSH access intact. Then add the selected rule:

```console
RULE="rule family=\"ipv4\" source address=\"$CLIENT_CIDR\" port port=\"8443\" protocol=\"tcp\" accept"
sudo firewall-cmd --zone="$FIREWALL_ZONE" --add-rich-rule="$RULE"
sudo firewall-cmd --permanent --zone="$FIREWALL_ZONE" --add-rich-rule="$RULE"
sudo firewall-cmd --zone="$FIREWALL_ZONE" --list-all
```

AWS additionally enforces its security group. Verify actual external
reachability; do not infer it from rule text or a successful local curl.

## 3. Check TLS and denial from the workstation

In the shell holding `LAB_DIR` and `GATEWAY_NAME`:

```console
PRAXIS_URL="https://$GATEWAY_NAME:8443"
CODE="$(curl --silent --show-error --cacert "$LAB_DIR/tls/ca.pem" \
  --output /dev/null --write-out '%{http_code}' "$PRAXIS_URL/v1/models")"
test "$CODE" = 401
```

Expected: trusted TLS succeeds and missing JWT returns `401`, without a
provider call. A TLS failure is not an authentication pass. Also verify:

- Without the private CA, certificate validation fails.
- With a different hostname/IP, hostname validation fails.
- Plain HTTP on 8443 does not return an inference response.
- Ports 8080, 8081, 8082, 9901 and 6379 are unreachable from the workstation.
- An unapproved source cannot connect to 8443.

The no-key automated regression test covers TLS/JWT checks with synthetic
providers, independent of this real guest:

```console
CONTAINER_ENGINE=podman python3 tests/remote-gateway/image.py
CONTAINER_ENGINE=podman python3 tests/remote-gateway/image.py --valkey
```

## 4. Harness and persistence checks

Issue separate JWTs for two test users. Follow [remote user setup](../quickstarts/remote-gateway/users.md),
using the test CA's public `ca.pem` and the HTTPS URL. Run the three harnesses
with memory, then uninstall that profile and repeat with Valkey. Use the
[harness acceptance checklist](harnesses.md), including quota exhaustion,
accounting, Valkey outages and restart recovery.

Both JWT callers currently share provider/API quotas. Token renewal must not
be presented as resetting or creating a personal quota. No paid provider call
is made by the TLS/JWT regression test; real harness tasks are a separate gate.
