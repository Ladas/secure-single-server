# Architecture overview

This page describes how the harness, OpenShell, model access, and host
deployment fit together. It is informational; deployment, configuration, and
validation procedures are in the linked guides.

Coding harnesses are useful because they can read a workspace, run tools, and
call a model. Those same capabilities raise questions about which files and
commands are available, where model traffic goes, who holds provider
credentials, and how a host is kept consistent. This design assigns those
responsibilities to separate components.

## Components

| Component | Role in the architecture | Boundary or limitation |
| --- | --- | --- |
| Harness | Provides the user experience for coding tasks, including prompts, model selection, and tool calls. | The harness itself does not define the host's filesystem or network boundary. |
| OpenShell | Runs harnesses and tools in sandboxes governed by filesystem and network policies. | The current deployment is operated by a trusted administrator; it is not a multi-tenant authorization system. |
| Praxis | Provides an optional model gateway for routing, provider credential custody, and configured shared usage limits. | Limits and routing depend on the selected Praxis profile and upstream. |
| vLLM | Serves a selected local model, such as Qwen, on a private inference host. | Its API should remain private and be reached through the configured model path. |
| bootc | Provides an optional repeatable RHEL environment managed by a container image. | Host image management does not preserve application or workspace data by itself. |

## Model access paths

| Model choice | Request path | What it means |
| --- | --- | --- |
| Local inference | Sandboxed harness → Praxis → private vLLM host | The model runs in the managed environment rather than through a hosted frontier-model API. The documented Qwen deployment uses a separate inference server; a co-located bootc path remains available for compatibility. |
| External frontier model | Sandboxed harness → Praxis → provider API, or a configured OpenShell provider profile → provider API | Requests are served by an external provider. Praxis can centralize provider credentials and apply its configured shared limits; a direct provider profile is another documented option. Provider terms and data handling apply to the selected service. |

The model path is separate from the execution boundary. OpenShell governs the
harness and its tools; the chosen model route determines where prompts and
responses are processed. When Praxis is used, sandbox policy can limit the
harness to the gateway while Praxis selects the approved upstream.

## Why the components are separated

| Concern | Role in this design |
| --- | --- |
| Workspace and tool access | OpenShell policies describe the sandbox's writable paths, read-only paths, approved binaries, and network destinations. |
| Model routing | Praxis can give the harness one gateway endpoint while selecting a local or external upstream. |
| Provider credentials | A gateway or configured OpenShell provider profile can keep provider credentials out of ordinary harness configuration. |
| Shared use | Praxis profiles can enforce shared request or token allowances; the exact semantics depend on the selected profile. |
| Host consistency | A bootc deployment can package the reviewed host environment and pinned workload configuration as a repeatable OS image. |

## Scope

This repository documents selected configurations of OpenShell, Praxis,
vLLM, and the harnesses. A component's presence does not imply that every
upstream feature, provider combination, workload, or hardware configuration
has been qualified. See the compatibility and validation records for the
combinations that have been exercised.

## Deployment and validation guides

- [Bootc deployment](../openshell-single-server/bootc.md) and [manual Podman deployment](../openshell-single-server/manual.md)
- [Local vLLM deployment](../../../bootc/VLLM.md) and [RHEL vLLM administration](../common/vllm.md)
- [OpenShell + Praxis](../openshell-praxis/README.md)
- [OpenShell Overview](../../../openshell/docs/README.md)
- [Compatibility matrix](../../testing/compatibility.md) and [testing guide](../../testing/README.md)
