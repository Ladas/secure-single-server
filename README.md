# Secure single-server AI harness

Secure single-server AI harness runs [OpenCode](https://github.com/anomalyco/opencode)
and [OpenClaw](https://github.com/openclaw/openclaw) on one dedicated RHEL 9
x86_64 host. [OpenShell](https://github.com/NVIDIA/OpenShell/tree/v0.1.4/docs)
enforces the execution boundary. For the integrated harness paths,
[Praxis](https://github.com/praxis/praxis) routes model traffic, while
[Red Hat bootc](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/using_image_mode_for_rhel_to_build_deploy_and_manage_operating_systems/index)
packages the reviewed deployment as a repeatable OS image.

> [!IMPORTANT]
> This is an experimental demonstration, not a production-ready platform. Use
> a disposable host for first evaluation and review the linked qualification
> evidence before extending a deployment.

## How It Works

The integrated request path is:

```text
OpenCode / OpenClaw → OpenShell sandbox → Praxis → approved model
```

OpenClaw supports bounded coding tasks through Praxis; see the
[OpenClaw walkthrough](docs/quickstarts/openshell-praxis/openclaw.md) and its test evidence.

- **Dedicated always-on execution.** Long-running agents continue on the
  server while your laptop disconnects. Workspaces, audit records, and cached
  model artifacts remain on the host.
- **Policy-enforced harnesses.** OpenShell confines each harness and its tools
  with declared filesystem, network, process, runtime, and service-account
  policies. The gateway records policy decisions for later review.
- **Centralized model access.** On the integrated paths, Praxis owns provider
  credentials and selects the approved upstream. The harness and sandbox do
  not hold provider keys.
- **Repeatable deployment.** Published bootc images carry the OpenShell CLI,
  service configuration, and pinned workload references. First boot pulls the
  selected control-plane and harness images into rootless Podman storage.

## Quickstart

The published bootc image can be booted on a bootc-enabled OS or run as an OCI
container with Podman. Booting it starts the complete OpenShell deployment;
running a shell in Podman lets you inspect the image. For a working Podman-only
model call, use the [Podman quickstart](docs/quickstarts/podman/README.md).

Before starting, have:

- Podman or a bootc enabled server
- A valid OpenAI API key and the exact ID of a model your account can access.

With these prerequisites, target a first model response in under five minutes.
Initial image downloads, bootc OS deployment, and local-model
loading add time(optional).

The published-image quickstart uses OpenCode. For OpenClaw, use the
[model and tool walkthrough](docs/quickstarts/openshell-praxis/openclaw.md) with
a checkout or image containing the new integration.

### Bootc-enabled operating system

Follow the [bootc quickstart](docs/quickstarts/bootc/README.md) to deploy the
published image, enter your OpenAI key, and connect to an OpenCode sandbox
configured for Praxis. It also links to local inference options.

### Podman

With Podman already running, follow the [Podman quickstart](docs/quickstarts/podman/README.md)
to inspect the bootc image or make a model call through Praxis. It includes the
required variables, credential prompt, and cleanup commands.

To install OpenShell, harnesses, and Praxis separately on a fresh VM or bare
metal, follow the [manual single-server guide](docs/quickstarts/openshell-single-server/manual.md)
and [Praxis installation walkthrough](docs/quickstarts/openshell-praxis/install.md).

The manual guide installs Git and Podman, clones the reviewed revision to the
service-readable `/opt/secure-single-server` path, and runs the installer from
that checkout. The installer verifies that the host provides Landlock ABI 3 or
newer before creating sandboxes. After the guide's `repo` and `os_run`
definitions are active, connect to an OpenCode sandbox with:

```bash
os_run "$repo/openshell/harnesses/opencode/connect.sh" --name opencode-dev
```

The connect entry point also accepts an optional remote command. For a simple
Bash session without editing the harness script, use:

```bash
os_run "$repo/openshell/harnesses/opencode/connect.sh" --name opencode-dev bash
```

## Remote gateway with user budgets

To connect local harnesses to a shared RHEL gateway, follow the
[MaaS and PriceTag deployment guide](docs/quickstarts/remote-gateway-pricetag/README.md).
It covers AWS or an existing RHEL host, one-command or manual installation,
real providers, USD budgets, dashboards and local OpenCode. Praxis routes
inference, MaaS manages finite-lived user keys, and PriceTag meters spending.

- [Provider configuration](docs/quickstarts/remote-gateway-pricetag/providers.md): endpoints,
  hidden credential prompts, protected-file automation and replacement.
- [User and key administration](docs/quickstarts/remote-gateway-pricetag/users.md): budgets,
  key lifecycle and available UI/API operations.
- [Mock benchmarks](docs/testing/pricetag-perf.md): separate test-host setup,
  configurable load and accounting/resource checks.

## What can I do with this setup?

For the shortest introduction to OpenShell's value, try the
[Streamlit before-and-after demo](docs/examples/streamlit-security/README.md).
It runs the same model-backed app first in an ordinary container and then in an
OpenShell sandbox, showing credential substitution and filesystem confinement
without using Praxis.

After that, try the
[OpenCode PR-candidate queue](docs/examples/opencode-pr-queue/README.md):

- Queue public GitHub issues or operator prompt files for a public repository.
- Optionally keep a longer batch alive in `tmux` after disconnecting from SSH.
- Collect one reviewable bundle per task containing the task, proposed patch,
  metadata, and report.
- Review the bundle on your workstation, then apply it and open a draft PR with
  your local Git and GitHub CLI credentials.

This scenario is issue/prompt-to-patch only. It does not perform pull-request
reviews, and the sandbox receives no GitHub token or GitHub write access.

All post-deployment scenarios are indexed in
[Example scenarios](docs/examples/README.md). Run them from the deployed
repository checkout: on a bootc image, use
`/usr/share/secure-single-server`; on a manual deployment, use
`/opt/secure-single-server`. Published image tags contain only the reviewed
revision from their build time, so use a rebuilt image or an updated manual
checkout when trying newer examples.

## Explore Further

- [Architecture walkthrough](docs/quickstarts/architecture-walkthrough/README.md):
  why each layer exists and what its evidence does not prove.
- [Manual single-server guide](docs/quickstarts/openshell-single-server/manual.md):
  OpenShell installation from a service-readable checkout, harness setup, Bash
  sandbox access, verification, and policy tests.
- [OpenShell trust model](openshell/docs/threat-model.md): the execution
  boundary and assumptions behind the current single-operator deployment.
- [Praxis integration](docs/quickstarts/openshell-praxis/README.md): model
  routing, quota semantics, and the experimental harness paths.
- [Private vLLM inference](bootc/VLLM.md): the separate CPU or GPU server used
  by the strongest validated local-model path.
- [Published bootc images](bootc/README.md): available OpenCode and OpenClaw
  variants and their deployment commands.
- [Testing and compatibility](docs/testing/README.md): how to reproduce the
  recorded checks and review the compatibility matrix.
- [Documentation map](docs/README.md): alternate deployment shapes and
  configuration guides.

## Notice and Disclaimer

This demonstration retrieves pinned external container images and, when local
inference is enabled, model artifacts. Those materials are governed by their
own terms, licenses, and security posture. You are responsible for reviewing
and complying with those terms and for verifying that the artifacts are
suitable for your environment. This repository is provided for demonstration
and evaluation purposes, without warranty of any kind.
