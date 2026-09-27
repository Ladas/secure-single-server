# Controlled network-policy qualification

`openshell/tests/openshell-policy.sh` uses a credential-free local HTTP fixture.
A permitted request must reach the server, increment its request counter, and
return the fixture's known HTTP 401 response. HTTP errors count as reachability.
The denied request must produce explicit proxy policy-denial evidence without
incrementing the destination counter. Missing Node, failed SSH, timeout or an
unreachable positive control fails the test; none proves enforcement.

The fixture owns two temporary sandboxes and a private host listener on port 18080 (use an isolated disposable host).
The runtime suite owns the gateway lifecycle. The test is separate from Praxis
inference, which requires `tests/openshell-praxis/smoke.sh` and a configured test
provider/model. Do not infer successful integration from a denial test alone.

Policies are per-binary and must match actual executable paths. The native schema
test parses all standalone and rendered integrated profiles with the pinned CLI.
Parsing does not prove runtime enforcement. Inspect actual supervisor logs and
kernel Landlock support; best-effort mode can degrade protection. See the
[threat model](threat-model.md) and [validation record](../../bootc/VALIDATION.md).
