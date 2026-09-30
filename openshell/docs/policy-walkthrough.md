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

`openshell/tests/policy-advisor.sh` extends the same fixture to the approval
workflow: it creates one deny-by-default sandbox, waits for a pending endpoint
proposal, approves it through `openshell/scripts/policy-approve.sh`, proves the
retry reaches the fixture, recreates the sandbox, and proves the grant is gone.
Its approval audit record is temporary and local to the test.

Policies are per-binary and must match actual executable paths. The native schema
test parses all standalone and rendered integrated profiles with the pinned CLI.
Parsing does not prove runtime enforcement. Inspect actual supervisor logs and
kernel Landlock support; best-effort mode can degrade protection. See the
[threat model](threat-model.md) and [validation record](../../bootc/VALIDATION.md).

## Policy boundaries

`openshell/tests/policy-boundary.py` checks every shipped policy against the
operator-owned maximum in `tests/policy-boundary/`. It requires the pinned
`openshell-prover` to return `within_boundary`, requires complete coverage of
the modeled filesystem, network, process, and Landlock domains, and rejects an
extra endpoint through a mutation control. CI installs OpenShell prover
`v0.1.2` by digest and runs this check in the UBI static lane.

When a profile intentionally widens access, update the matching boundary in the
same reviewed change. Treat the boundary as the reviewed maximum, not something
to regenerate automatically from the candidate. After the change, run:

```bash
python3 openshell/tests/policy-boundary.py
```

Set `OPENSHELL_PROVER_BIN` when using a prover binary outside `PATH`.
