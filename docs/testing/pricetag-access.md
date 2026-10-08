# PriceTag: optional public HTTPS access

Start with the restricted [AWS installation](aws-pricetag.md). This page is a
later AWS-administrator operation, not part of initial setup. Restore the launch
session using [AWS operations](aws-operations.md) before running these blocks.
All AWS credentials stay in the administrator's own workstation terminal.


Keep the initial deployment restricted. Run this section only after the real
server passes client and authorization checks and you choose to allow users
from any IPv4 address. The performance server stays restricted.

The endpoint remains **HTTPS on port 8443**. Opening the security-group rule
removes the source-IP restriction; it does not remove inference JWT validation,
dashboard login, admin authorization, Origin checks or USD enforcement.
Inference, user dashboards and the admin dashboard currently share this port:
**the admin login/routes will also be reachable from any IPv4 address**, with
PriceTag enforcing the authenticated role. A security group cannot distinguish
URL paths. If admin access must remain IP-restricted, implement and test a
separate application/listener boundary before opening this shared listener.

Non-expiring JWTs still require manual revocation/rotation. Existing browser
cookies can survive JWT revocation for seven days; global session-secret
rotation is the available emergency logout for all browsers. Retain the
request-rate limit, review service errors and maintain encrypted backups.

### TLS and hostname

For ordinary browser users, obtain a publicly trusted server certificate for
the public hostname. Prefer choosing that DNS name at initial preparation:
it is included in both the certificate and the dashboard's explicit allowed
Origins. DNS/certificate issuance and automatic renewal are operator-managed;
this deployment does not provision them. A private test CA can remain for
managed clients that explicitly trust it, but opening ingress does not make
browsers trust that CA automatically.

If replacing the laboratory certificate on RHEL, validate the new chain/key,
check that it covers `GATEWAY_HOST`, then install them and restart Praxis using the `svc` function from image
loading:

```console
sudo scripts/remote-gateway/credentials check-tls \
  --cert /root/pricetag-tls/fullchain.pem --key /root/pricetag-tls/privkey.pem
sudo openssl x509 -in /root/pricetag-tls/fullchain.pem -noout -checkhost "$GATEWAY_HOST"
sudo install -o root -g praxis-svc -m 0640 /root/pricetag-tls/fullchain.pem \
  /etc/praxis-pricetag/gateway/tls.pem
sudo install -o root -g praxis-svc -m 0640 /root/pricetag-tls/privkey.pem \
  /etc/praxis-pricetag/gateway/tls-key.pem
sudo restorecon -R /etc/praxis-pricetag/gateway
svc systemctl --user restart pricetag-gateway
```

The hostname check above is for a DNS name; IP certificates need the
corresponding IP SAN check. Back up the existing pair privately before changing
it. Arrange for renewal to update both files and restart the gateway. If the
public hostname changes, also update `manual_jwt` dashboard `allowed_origins`
in `gateway.json` to the new exact `https://HOST:8443` origin and restart.
Keep `https://localhost:8443` for on-host administration. Update clients to the
new URL and certificate trust; the user JWT issuer/audience do not change.

### Change only the real VM's HTTPS rule

Run on the workstation with the launch session restored and AWS credentials
loaded. Additional IAM permission `ec2:ModifySecurityGroupRules` is needed.
Changing the launch array to `--https-access public` does not update an existing
VM, and `scripts/aws/https-access` adds restricted HTTPS only when no different HTTPS rule is recorded; it is not a general IP-update tool.
Use the existing rule's ID for this transition.

Verify the real VM against its journal and retain a recovery copy:

```console
aws_test_verify pricetag-real
REAL_STATE=".state/$RUN_PREFIX-pricetag-real.json"
cp -n "$REAL_STATE" "$REAL_STATE.before-public"
REAL_SG=$(jq -er '.SecurityGroupId' "$REAL_STATE")
REAL_HTTPS_RULE=$(aws ec2 describe-security-group-rules --region "$REGION" \
  --filters "Name=group-id,Values=$REAL_SG" --output json | \
  jq -er '[.SecurityGroupRules[] | select(.IsEgress == false and .IpProtocol == "tcp"
    and .FromPort == 8443 and .ToPort == 8443 and .CidrIpv4 != null)] |
    if length == 1 then .[0].SecurityGroupRuleId else error("Expected exactly one IPv4 HTTPS rule") end')
printf 'Real server security group: %s; HTTPS rule: %s\n' "$REAL_SG" "$REAL_HTTPS_RULE"
```

Stop on any verification/query error. Confirm these are the **real** server's
resources before running the mutation:

```console
HTTPS_CIDR=0.0.0.0/0
HTTPS_ACCESS=public
aws ec2 modify-security-group-rules --region "$REGION" --group-id "$REAL_SG" \
  --security-group-rules \
  "SecurityGroupRuleId=$REAL_HTTPS_RULE,SecurityGroupRule={IpProtocol=tcp,FromPort=8443,ToPort=8443,CidrIpv4=$HTTPS_CIDR}" \
  --no-cli-pager
```

This changes only the selected TCP 8443 rule. SSH remains restricted and the
performance VM's security group is untouched. This is IPv4 access; no IPv6
listener/ingress rollout is included.
[AWS rule modification reference](https://docs.aws.amazon.com/cli/latest/reference/ec2/modify-security-group-rules.html).

After AWS reports success, reconcile the real VM's local journal. The following
checks the entire observed ingress against the expected new state before
saving it with the existing atomic journal writer:

```console
python3 - "$REAL_STATE" "$REGION" "$HTTPS_CIDR" "$HTTPS_ACCESS" <<'PYJOURNAL'
import copy, importlib.machinery, importlib.util, ipaddress, json, sys
from pathlib import Path
loader = importlib.machinery.SourceFileLoader('rhel_vm', 'scripts/aws/rhel-vm')
spec = importlib.util.spec_from_loader(loader.name, loader)
vm = importlib.util.module_from_spec(spec)
loader.exec_module(vm)
path, region, cidr, access = sys.argv[1:]
state = json.loads(Path(path).read_text())
assert state['Region'] == region and state['Scenario'] == 'remote-gateway'
network = ipaddress.ip_network(cidr, strict=True)
assert network.version == 4 and ((access == 'public' and cidr == '0.0.0.0/0') or
                                (access == 'restricted' and network.prefixlen == 32))
desired = copy.deepcopy(state)
rules = [r for r in desired['Ingress'] if r.get('IpProtocol') == 'tcp'
         and r.get('FromPort') == 8443 and r.get('ToPort') == 8443]
assert len(rules) == 1
rules[0]['IpRanges'] = [{'CidrIp': cidr}]
desired['HttpsAccess'] = access
aws = vm.Aws(region, None, False)
vm.check_identity(aws, state['AccountId'])
groups = aws.call('ec2', 'describe-security-groups', group_ids=[state['SecurityGroupId']])['SecurityGroups']
assert len(groups) == 1
vm.check_owned(groups[0], state)
vm.check_ingress(groups[0], desired)
vm.update_state(Path(path), desired)
print('Observed ingress verified; real-server journal updated.')
PYJOURNAL
aws_test_verify pricetag-real
if [ -f ".state/$RUN_PREFIX-pricetag-perf.json" ]; then
  aws_test_verify pricetag-perf
fi
```

If reconciliation fails, the AWS rule may already be public. Inspect the
reported mismatch and reconcile or roll back; do not relaunch or edit the
journal to hide unrelated drift. Verify from a second client outside the old
`/32`: HTTPS login loads, unauthenticated inference returns 401, a valid caller
can infer and view their own usage, and an ordinary user cannot administer
budgets. Browser writes require the configured exact public Origin.

### Restore restricted access

Use the same real security group and HTTPS rule ID. Recover the original
workstation CIDR from the saved journal, then modify that rule back:

```console
HTTPS_CIDR=$(jq -er '.Ingress[] | select(.FromPort == 8443) | .IpRanges[0].CidrIp' \
  "$REAL_STATE.before-public")
HTTPS_ACCESS=restricted
aws ec2 modify-security-group-rules --region "$REGION" --group-id "$REAL_SG" \
  --security-group-rules \
  "SecurityGroupRuleId=$REAL_HTTPS_RULE,SecurityGroupRule={IpProtocol=tcp,FromPort=8443,ToPort=8443,CidrIpv4=$HTTPS_CIDR}" \
  --no-cli-pager
```

Rerun the journal-reconciliation block with these variables, then verify the
real VM and the performance VM if one was launched. If your workstation IP changed, choose its current public `/32`
explicitly instead. No change to JWTs, TLS or spending records is needed when
changing only the source-IP policy.
