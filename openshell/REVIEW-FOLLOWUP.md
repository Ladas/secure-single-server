# PR #3 review follow-up in PR #4

The September 25 review is addressed here alongside bootc so the same shared
scripts and gateway template are exercised by the OS images. This is a record
of fixes and narrowed claims, not a declaration that all inference combinations
are qualified.

| Finding | Change and evidence |
| --- | --- |
| F01: readonly variable collision | Distinct harness config variable; offline create tests cover standalone/integrated paths, unknown profiles, missing values and provider arguments. |
| F02: quoted policy port | Validated integer port, numeric rendered YAML, safe JSON model rendering. All 16 profiles parsed with the pinned native CLI on AWS. |
| F03: Praxis manifest damage | OpenShell is an independently managed add-on; the all-in-one scenario and manifest stay unchanged. AWS install/status/reinstall/remove/status/reinstall lifecycle and final Praxis uninstall passed with dummy secrets. |
| F04: false denial success | HTTP 200/401/403/500 regression proves all responses count as reachable. The new fixture requires a server counter, a successful positive control, and explicit policy-denial evidence. The AWS positive control currently fails; policy enforcement and integrated inference remain unqualified. No success is reported for this failure. |
| F05: unfinished harness integration | Codex/OpenClaw reject integrated `--config` before creation. OpenCode config remains experimental. No supported real-provider or tool-task claim; the pinned AWS sandbox cannot resolve the proposed Praxis alias. |
| F06: runtime CI lifecycle | Manual-only opt-in disposable RHEL runner, explicit prerequisites, one gateway owner/lifecycle, native schema checks, synthetic credential test and strict policy qualification. Common-script/test/bootc paths trigger static checks. Workflow lint passed. Skipped runtime jobs are not evidence. |
| F07: installer ownership/persistence | Explicit locked owner, user bus and lingering, scoped delegation without manager restart, private CLI extraction, pinned CLI replacement, health polling, independent file hashes and recovery/removal contract. Native AWS install and rerun passed. |
| F08: credential contract | SSH uses isolated client configuration with no key forwarding. Standalone creation accepts explicit provider bindings, disables automatic provider discovery, and integrated mode rejects direct bindings. Fresh gateways require explicitly imported provider profiles. Synthetic canary tests are separate from real inference qualification. |
| F09: documentation/trust | Correct RHEL account, paths, health checks, prerequisites and mode boundaries. Removed inline-key, workspace-mount/persistence, blanket GitHub read-only and shared-host trust claims. OpenClaw opens a shell until service/authentication are qualified. Removed internal implementation plans. |
| F10: creation/session lifecycle | Explicit detached creation and JSON readiness. AWS creation without a TTY reached Ready and CLI execution passed. Retained harness tasks/browser sessions remain outside supported claims. |

See [bootc validation](../bootc/VALIDATION.md) for deployment evidence. The remaining
network/inference/session qualification is deliberate visible scope, not a passed
test or an implicit production-support promise.
