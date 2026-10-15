# Documentation map

Start with the [repository overview](../README.md), then follow the route that
matches your decision. You do not need to read every document in this
repository; the guides below are separated by the question they answer.

## Recommended route

1. **Understand the architecture.** Read
   [why this architecture exists](quickstarts/architecture-walkthrough/README.md)
   before choosing a deployment. It explains what each layer protects, what it
   does not protect, and which evidence is accepted.
2. **Deploy a sandboxed harness.** Use
   [OpenShell](https://github.com/NVIDIA/OpenShell/tree/v0.1.3/docs) through the
   [manual container guide](quickstarts/openshell-single-server/manual.md) or
   [bootc deployment guide](quickstarts/openshell-single-server/bootc.md) to deploy [OpenCode](https://github.com/anomalyco/opencode) or
   [OpenClaw](https://github.com/openclaw/openclaw) on one trusted RHEL host.
3. **Add model routing.** Use
   [Praxis](https://github.com/praxis/praxis) through the
   [OpenShell + Praxis guide](quickstarts/openshell-praxis/README.md) when the
   sandboxed harness should use a gateway instead of holding provider
   credentials.
4. **Choose the inference path.** Follow the
   [private vLLM workflow](quickstarts/common/vllm.md) or
   [provider setup](quickstarts/common/providers.md) after selecting the
   gateway route.
5. **Reproduce the evidence.** Use the [testing guide](testing/README.md) and
   [compatibility matrix](testing/compatibility.md) before treating a
   combination as qualified.
6. **Plan the next capability.** Use the [roadmap](roadmap.md) to separate
   accepted behavior from work still in progress.

## Choose by outcome

| If you need to… | Use |
| --- | --- |
| Explain or review the complete system | [Architecture walkthrough](quickstarts/architecture-walkthrough/README.md) |
| Install OpenShell and harness containers separately | [Manual single-server deployment](quickstarts/openshell-single-server/manual.md) |
| Deploy or evaluate OpenShell quickly | [Single-server bootc quickstart](quickstarts/bootc/README.md) |
| Inspect the bootc image or make a model call with Podman | [Podman quickstart](quickstarts/podman/README.md) |
| Combine OpenShell with Praxis | [OpenShell + Praxis guide](quickstarts/openshell-praxis/README.md) |
| Serve users from accounts on one RHEL host | [All-in-one gateway](quickstarts/all-in-one/README.md) |
| Connect harnesses on remote client machines | [Remote HTTPS/JWT gateway](quickstarts/remote-gateway/README.md) |
| Try a post-deployment workflow | [Example scenarios](examples/README.md) |
| Deploy the OS image | [bootc guide](../bootc/README.md) |
| Configure harnesses, providers, or quotas | [Common configuration index](quickstarts/common/README.md) |
| Inspect OpenShell policies and boundaries | [OpenShell documentation](../openshell/docs/README.md) |
| Reproduce validation or add a new combination | [Testing guide](testing/README.md) |
| Understand future scope and acceptance | [Roadmap](roadmap.md) |

## Reading rules

- The recommended route is the sandboxed **harness → OpenShell → Praxis →
  inference** path. Other guides describe alternate deployment shapes, not
  interchangeable substitutes.
- Quickstarts tell you how to run a documented path. Validation records and
  the compatibility matrix determine what is qualified.
- Trust-model and quota documents define boundaries that are easy to miss when
  reading configuration alone.

## Upstream references

- [OpenCode](https://github.com/anomalyco/opencode)
- [OpenClaw](https://github.com/openclaw/openclaw)
- [OpenShell documentation](https://github.com/NVIDIA/OpenShell/tree/v0.1.3/docs)
  and [sandbox overview](https://github.com/NVIDIA/OpenShell/blob/v0.1.3/docs/how-it-works/sandboxes/overview.mdx)
- [Praxis framework](https://github.com/praxis/praxis)
- [Praxis experimental gateway](https://github.com/praxis-proxy/experimental)
- [Red Hat bootc](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/using_image_mode_for_rhel_to_build_deploy_and_manage_operating_systems/index)
- [vLLM documentation](https://docs.vllm.ai/en/latest/) and
  [CPU installation](https://docs.vllm.ai/en/v0.19.0/getting_started/installation/cpu/)

This repository tracks only its pinned deployment contracts and acceptance
evidence. Consult upstream documentation for general project features that
this deployment does not qualify.

## Next step

Start with the [architecture walkthrough](quickstarts/architecture-walkthrough/README.md).
If you already understand the system and only need a disposable evaluation,
use the [bootc quickstart](quickstarts/bootc/README.md).
