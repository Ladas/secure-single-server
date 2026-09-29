# Install the experimental OpenShell add-on

Install [Praxis all-in-one](../all-in-one/README.md) first on RHEL 9 x86_64.
Its loopback management API requires TLS/mTLS. The installer registers one
service-operator identity; separate user/workspace access is not implemented.
Bootc hosts instead use
[bootc reconciliation](../../../bootc/README.md).

## 1. Administrator: transfer the addon

From the reviewed workstation checkout, reuse `RHEL_HOST` and `SSH_OPTIONS`
from the all-in-one installation, in the same Bash shell:

```console
ssh "${SSH_OPTIONS[@]}" "$RHEL_HOST" \
  'install -d -m 0700 ~/secure-single-server-deploy/{configs,scripts,openshell}'
scp "${SSH_OPTIONS[@]}" -pr configs/common configs/openshell-praxis \
  "$RHEL_HOST:~/secure-single-server-deploy/configs/"
scp "${SSH_OPTIONS[@]}" -pr scripts/common scripts/openshell-praxis \
  "$RHEL_HOST:~/secure-single-server-deploy/scripts/"
scp "${SSH_OPTIONS[@]}" -pr openshell/configs openshell/scripts openshell/harnesses \
  "$RHEL_HOST:~/secure-single-server-deploy/openshell/"
ssh -t "${SSH_OPTIONS[@]}" "$RHEL_HOST" 'bash -l'
```

## 2. Administrator: install and verify

In that RHEL session:

```console
cd ~/secure-single-server-deploy
sudo dnf install -y curl python3 podman policycoreutils
```

```bash
sudo scripts/common/status
sudo cat /etc/praxis/gateway.scenario   # remains all-in-one
sudo scripts/openshell-praxis/install --owner openshell-svc
sudo scripts/common/status
curl -fsS http://127.0.0.1:8091/healthz
```

The add-on verifies the Praxis managed manifest and never rewrites its scenario,
configuration, quotas or secrets. The dedicated locked `openshell-svc` account
owns the rootless gateway; `praxis-svc` continues to own Praxis. Delegation is
scoped to the OpenShell user manager and applied without restarting it. Lingering
keeps services running after logout. The installer polls health and CLI access.

Rerun the same installer after failure; machine keys and data are retained. It
refuses an existing data directory owned by another account or unmanaged config.
Remove the add-on with `sudo openshell/scripts/uninstall.sh`, then rerun
`sudo scripts/common/status`. Removal stops the gateway and removes its unit;
it retains account, lingering, CLI, configuration, keys, containers and workspaces.
Export and delete sandbox work before final host disposal. Praxis uninstall
remains its independent managed lifecycle; drift checks stay enabled.

Praxis listens on loopback 8080 (OpenAI inference) and 8081 (Anthropic inference).
Its admin health is private inside the container; use `scripts/common/status`,
not a host health URL. OpenShell uses loopback 8090 (management) and 8091 (health).
Management uses HTTPS and a client certificate mapped to the operator identity.
Keep its keys private and its port on loopback. The health endpoint remains HTTP;
its success does not prove authenticated management or inference access.

## 3. Publish public recipes

Make only the public recipes available to ordinary accounts. Keep `material/`,
provider credentials and the rest of the administrator's bundle private:

```console
sudo install -d -m 0755 /opt/praxis/recipes/scripts/common /opt/praxis/recipes/configs \
  /opt/praxis/recipes/openshell/scripts
sudo cp -R openshell/configs openshell/harnesses /opt/praxis/recipes/openshell/
sudo install -m 0644 openshell/scripts/lib.sh openshell/scripts/harness-lib.sh \
  /opt/praxis/recipes/openshell/scripts/
sudo cp -R configs/openshell-praxis /opt/praxis/recipes/configs/
sudo install -m 0644 scripts/common/lib.sh /opt/praxis/recipes/scripts/common/lib.sh
sudo chmod -R a+rX /opt/praxis/recipes
sudo restorecon -RF /opt/praxis/recipes
```

Read [user access limitations](users.md) before handing access to another person.
Gateway health does not establish working model traffic or sandbox isolation.
