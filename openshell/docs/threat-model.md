# OpenShell experimental deployment boundaries

Use a disposable, trusted single-operator host. The loopback management API allows
unauthenticated local users and controls its owner's rootless Podman socket.
Loopback is not per-user authorization; sandbox JWTs do not authenticate ordinary
local operators. This is not a secure shared-host multi-tenant deployment.

Policies express per-binary network allowlists and filesystem permissions. Their
presence is not proof of enforcement. Test a controlled reachable destination,
observe server-side request counts and explicit policy denial, and establish
working sandbox execution first. An HTTP 401/403 from the destination is reachable
traffic; SSH errors and timeouts are inconclusive. The runtime policy fixture
requires a working 401 positive control and a distinct policy-denial response
without a destination request. It fails closed when the result is inconclusive.

`landlock.compatibility: best_effort` can degrade filesystem protection. Record
the actual supervisor/kernel enforcement result; host SELinux Enforcing alone is
insufficient. The gateway Quadlet disables SELinux labeling to operate its Podman
socket. This is distinct from per-container confinement. No blanket enforcement
claim is made for unqualified kernel/profile combinations.

`include_workdir` grants policy permissions; it neither mounts a host checkout nor
proves persistence. Deleting a sandbox can destroy its work. Export data before
removal and test any retained-task/session requirement separately. Detached
creation retains a sandbox main process, not necessarily a harness launched later
through an SSH session. Admission and resource ceilings require deployment work.

The dev policy limits GitHub API methods but does not impose read-only semantics
on Git-over-HTTPS to github.com. Allowed endpoints can receive data from a malicious
harness; allowlists do not inspect model prompts or guarantee trustworthy code.

Images are digest-pinned for repeatability, not a claim of audited contents.
Harness CLIs are preinstalled; profiles permitting package registries still permit
package downloads during later work.

SSH helpers use an isolated client configuration and forward no provider keys.
Standalone mode accepts an explicit OpenShell provider binding; use the native
CLI's environment lookup after a hidden prompt and start with synthetic credentials.
Integrated mode rejects direct provider bindings; Praxis holds upstream secrets.
Actual credential rewriting and real-provider tool tasks remain qualification
requirements. Never place real credentials in images, logs, command arguments,
Git or test artifacts. See [AWS validation](../../bootc/VALIDATION.md).
