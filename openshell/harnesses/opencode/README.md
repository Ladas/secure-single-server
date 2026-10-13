# OpenCode harness

OpenCode provides the coding-agent experience: prompts, model interactions,
and tool calls. This directory packages its lifecycle scripts, pinned image
reference, and OpenShell profiles; it does not replace OpenCode with a custom
agent.

Deploy and test OpenCode from the
[OpenShell single-server guide](../../../docs/quickstarts/openshell-single-server/README.md).
The optional Praxis route is documented separately for administrators who
select it. The [0.1.3 upgrade tests](../../../docs/testing/upgrade-0.1.3.md)
exercise model responses, streamed write and bash tools, independent file
readback, and policy denials with controlled model fixtures. Qualify the intended
real provider and model separately. In that route, tools do not receive direct vLLM or cloud-provider
access. In standalone OpenShell mode, selected model endpoints remain governed
by the harness policy.

The preinstalled harness image is digest-pinned in `openshell/configs/images.env`.

The `review-github` profile adds delegated PR review: `review.sh` sends a
batch of PRs as one bounded agent turn and `collect.sh` retrieves the report
artifacts. See the [review service guide](../../../docs/development/review-service.md).
