# OpenClaw → OpenShell → Praxis qualification

> **Historical results:** This page records the earlier OpenShell 0.1.2 and
> OpenClaw pins shown below. Its real-GPU results have not been repeated on the
> upgraded versions. See the [OpenShell 0.1.3 upgrade qualification](upgrade-0.1.3.md)
> for current pins, controlled model/tool tests, and limits.

Recorded on 2026-10-09 using this PR's source tree in AWS `us-east-1`.
This qualifies bounded read/write `openclaw agent exec` tasks in the `dev` profile.
The [deployment walkthrough](../quickstarts/openshell-praxis/openclaw.md)
describes credentials, model selection, and manual/bootc commands.

## Environment and pins

- Disposable RHEL 9 x86_64 `m7i.2xlarge`: Podman 5.8.2, enforcing SELinux,
  rootless OpenShell owned by `openshell-svc`.
- Separate private `g6.2xlarge`: one NVIDIA L4, NVIDIA 580 open driver,
  pinned vLLM and Qwen3-8B from the [recorded images.env](https://github.com/redhat-et/secure-single-server/blob/886eed8edc5052a40650381185f6da51c14fdc31/configs/vllm/images.env).
  Inference port 8000 is restricted to the OpenShell host's security group.
- OpenShell `v0.1.2-rhaiv.0`; the recorded control-plane/workload digests are in
  [OpenShell images.env at the qualification commit](https://github.com/redhat-et/secure-single-server/blob/886eed8edc5052a40650381185f6da51c14fdc31/openshell/configs/images.env).
- OpenClaw workload digest:
  `sha256:de12000bc8c251e868519bb86ed975458bf3f2ff63c6ebc2eece4bc769f14b69`.
- Praxis workload digest:
  `sha256:a3006352106c2264427faa79b57cf7b49287f3f9bfffe9b2eef869d3429988e8`.
- RHEL bootc parent digest:
  `sha256:cfe6b13fa436d39088cc525254f5de9f4e0c7da8b8f0b44b926acd11cdeb42d7`.

## Results

| Check | Result |
| --- | --- |
| Native pinned OpenClaw → Praxis → bearer-authenticated synthetic model | Passed: streamed write tool, exact file contents, follow-up model turn |
| Invalid upstream key | Passed: nonzero client exit, no successful tool file |
| Custom keyed-provider prefix (`/providers/team`) | Passed: streamed tool/continuation through prefix rewrite and credential injection |
| Credentialless synthetic upstream | Passed; Praxis removes the client placeholder |
| Actual OpenShell sandbox with synthetic model | Passed: streamed write and continuation; independent file verification |
| OpenShell network and credential controls | Passed: Praxis positive control, direct fixture/cloud denied with EACCES, provider key environment absent |
| Policy schema and reviewed boundary prover | Passed: all 19 shipped policies, invalid-schema and boundary-mutation controls |
| Offline argument/config/runner regressions | Passed: model JSON escaping, custom-provider path selection, unsupported options, provider injection rejection, safe stdin task transport, SSH error propagation |
| RHEL bootc base and OpenClaw image build | Passed on AWS; image contract checks passed |
| Booted bootc OS deployment | Not run in this qualification; build/container checks do not prove reboot deployment |
| Paid OpenAI or keyed private production endpoint | Not run; authenticated synthetic API validates credential routing, not account/model compatibility |
| Real Qwen3-8B GPU read/write task | Passed: generated code; real read/write tool calls with no tool failures; three independent Node assertions through sandbox SSH |

The pinned sandbox permits signals to a child PID but denies process-group
signals (`kill(-pgid, 0)` and group termination return `EPERM`). OpenClaw's
`exec` tool then reports uncertain process-tree cleanup and fails the command.
The shipped client configs exclude `exec`; read/write model tasks are the
qualified scope. Generated code runs through ordinary sandbox SSH for independent
verification. Native container execution alone does not expose this limitation.

The initial OpenShell settings poll also advances the policy generation and
closes streams opened before the poll. Creation now waits for that first poll
before uploading model config. The vLLM template disables thinking per request
and uses a 300-second provider request ceiling within the bounded task timeout. This prevents a successful retry from retaining
an earlier uncertain cleanup result.

SQLite initially failed because it selected policy-denied `/var/tmp` for a
temporary FTS table. The runner sets `SQLITE_TMPDIR=/tmp`, preserving the policy
boundary. Native container success alone did not catch this failure; the actual
OpenShell test now covers it.

Automated command execution, browser login, gateway service commands, retained conversation sessions,
`--backend`, Anthropic Messages translation, and ordinary-user enrollment are
outside these results. Cloud dev also allows selected GitHub/npm endpoints;
the dedicated vLLM profile permits only the Praxis model endpoint.

## Repeat the checks

Offline tests:

```bash
python3 tests/openshell-praxis/offline.py
python3 bootc/tests/inference.py
python3 openshell/tests/regressions.py
python3 openshell/tests/policy-boundary.py  # pinned openshell-prover required
python3 openshell/tests/schema.py          # pinned native OpenShell CLI required
```

On native Linux x86_64 with Podman and PyYAML:

```bash
python3 tests/openshell-praxis/openclaw-native.py
```

This starts only the pinned client/gateway and a synthetic provider. It checks
both upstream auth modes and saves sanitized evidence under
`evidence/mocked-provider/openclaw-native.json`. `CONTAINER_ENGINE=docker` selects
Docker on the hosted GitHub runner.

On a disposable RHEL host with OpenShell already installed:

```bash
sudo env OPENSHELL_TEST_OWNER=openshell-svc \
  bash tests/openshell-praxis/openclaw-runtime.sh
```

Ports 18000/18080 must be free. It creates and deletes its sandbox, fixture, and
Praxis container; no real credentials are required. The full
`openshell/tests/runtime.sh` also runs this check.

For an already-ready real Praxis upstream, execute as its OpenShell service
owner from a readable checkout:

```bash
export OPENSHELL_MODEL_ID=qwen3-8b
export PRAXIS_API_PREFIX=/vllm  # mutable /vllm route; omit for bootc/cloud
export OPENCLAW_TEST_CONFIG="$PWD/configs/vllm/openclaw"
bash tests/openshell-praxis/openclaw-real.sh
```

Exploratory model-authored tests were inconsistent: one suite passed, while
other attempts used ESM imports in `.cjs` or the wrong Node test assertion API.
The shipped real acceptance therefore asks for a small implementation and checks
it with trusted assertions; it qualifies transport/file tools, not general model
coding quality. Failures are never converted to success.

The real test requires actual read and write tool calls, zero reported tool
failures, a successful final response, and three independent arithmetic tests
against the generated CommonJS module in a fresh sandbox SSH process.
It deletes its sandbox.
Credentials remain at Praxis. Wait for model readiness before running it.

## Continuous checks

[Validate OpenShell demos](https://github.com/redhat-et/secure-single-server/blob/main/.github/workflows/openshell-validate.yml) runs
offline regressions and the pinned native client/gateway contract on hosted
runners for relevant PRs and main changes. Artifacts contain sanitized evidence.
Its actual OpenShell runtime job is opt-in on a disposable RHEL runner, only
from `main` via workflow dispatch with `OPENSHELL_SELF_HOSTED=true`.
Privileged self-hosted runners never execute pull-request code.

[Build bootc images](https://github.com/redhat-et/secure-single-server/blob/main/.github/workflows/bootc-images.yml) already selects
harness images when these scripts/configs change. The OpenClaw image contract
now requires the runner, renderer, and both provider-policy configurations.
Real-model acceptance remains an opt-in check against a prepared model server;
CI fixtures need no paid provider keys or GPU.
