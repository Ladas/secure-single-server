# vLLM bootc validation — 2026-09-28

Validation used real Qwen3-8B weights on AWS, with rootless Podman workloads,
SELinux enforcing, and read-only `/usr`. No cloud model provider or provider
credential was used. Images were transferred as OCI archives into root's
container storage and applied with `bootc upgrade`; registry distribution was
not tested.

## Inputs

| Component | Tested input |
| --- | --- |
| CPU host | m7i.2xlarge, 8 vCPUs, 32 GiB, 100 GiB EBS, us-east-1 |
| GPU host | g6.2xlarge, one NVIDIA L4 (23,034 MiB), 32 GiB, 200 GiB EBS, us-east-2 |
| OS | RHEL 9.8 bootc, kernel `5.14.0-687.50.1.el9_8.x86_64` |
| NVIDIA | Open driver `580.178.04`, compiled during OS build; Container Toolkit `1.20.1` / CDI |
| OpenShell | `v0.1.2-rhaiv.0`, source `5e184ecbce9868074af4c4d59731ecf19a0d6e37` |
| OpenCode | `1.18.31`, existing pinned workload image |
| vLLM | `0.19.0` GPU / `0.19.0-x86_64` CPU |
| Model | `Qwen/Qwen3-8B`, revision `b968826d9c46dd6066d109eabc6255188de91218` |

RHEL base digest:
`sha256:cfe6b13fa436d39088cc525254f5de9f4e0c7da8b8f0b44b926acd11cdeb42d7`.
Workload digests are recorded in [vLLM pins](../configs/vllm/images.env),
[OpenShell pins](../openshell/configs/images.env), and the existing
[Praxis defaults](../scripts/common/lib.sh).

Final **booted** OCI manifests reported by `bootc status`:

- CPU OpenCode: `sha256:5ca8b569d6f5d0fe9454ea4b99f2ed53fba5d276f28c77b5650a6bf5d85c861a`
- GPU OpenCode: `sha256:3b73a7d7cc23e98e97470d3bc3e5759c6afbb7a29d04f32bd4c5def73a497dd2`

Both deployments' vLLM launcher, Praxis config, OpenCode provider template and
local policy were SHA-256 compared against this checkout. Final defaults are
BF16, 16,384 context tokens, one sequence, eager execution, Hermes tool parsing,
and thinking disabled. OpenCode's output limit is 2,048 tokens.

## Checks

Both CPU and GPU base/Codex/OpenCode/OpenClaw OS variants built and passed
`bootc/test-images` (eight images). These image checks do not qualify local
Codex/OpenClaw adapters. Build, profile, provider rendering, isolation and
selector regression tests passed, as did ShellCheck, OpenShell static checks
and the shared gateway static suite.

Both final OpenCode hosts passed `bootc/test-host`: SELinux enforcing,
read-only `/usr`, healthy Praxis/OpenShell, and loopback listeners. Both modes
returned real nonempty Qwen completions directly and through Praxis. CPU
selection rejected GPU activation when NVIDIA host components were absent,
preserving the CPU selection.

Both final deployments passed `bootc/test-inference` in freshly created
OpenCode sandboxes after reboot. The smoke test checks a positive Praxis
request, explicit denied connections to vLLM port 8000 and `api.openai.com:443`, corresponding OpenShell
audit records, a streamed OpenCode response, and a bash-created file whose
contents are independently read back. This avoids accepting a model's claim
that a command ran as proof of tool execution. See
[`bootc/test-inference`](test-inference) to repeat the test.

CPU and GPU disable/re-enable retained the model cache, stopped port 8000,
and returned HTTP 502 from Praxis while the upstream was unavailable. Re-enabling served
real completions again from the retained cache. Cached model loading was also
exercised by the OS update/reboot on both hosts.

## Scope and limits

- OpenCode's writable local dev profile is the supported harness path. It
  permits only Praxis network access; package/GitHub access is not included.
- The older OpenShell host-mapping blocker in [the September 25 report](VALIDATION.md)
  is fixed by the coordinated control-plane pin update. The ODH fork still
  omits the managed `openshell inference` command; this uses an explicit policy
  endpoint instead.
- CPU inference is functional but slow on eight vCPUs. This is a functional
  demonstration, not a throughput or coding-quality benchmark. Cached reboot
  still requires reading roughly 16 GB of weights from disk.
- The disposable GPU instance remained in EC2 `shutting-down` during cleanup
  and required a force-termination request. The cause was not diagnosed;
  graceful EC2 termination is not qualified by these results.
- Offline startup, registry-failure recovery, OS rollback, Secure Boot key
  enrollment, sustained concurrency, and other GPU/CPU models were not qualified.
- The GPU build resolves signed NVIDIA 580-stream RPMs at build time. Preserve
  the resulting OS digest for deployment; rebuilding later can select newer
  packages. The workload and model references remain immutable.

## Cleanup

The disposable GPU instance was confirmed terminated, and its temporary security
group and imported key pair were deleted. The reused builder and CPU test host
were confirmed stopped. Temporary transfer keys and security-group rules were
removed. Operator logs are retained outside the repository under
`~/.secure-single-server-tests/vllm-20260928/`.
