# Example scenarios

These examples begin after a reviewed deployment is already running. Each one
opens with the outcome and the shortest safe path, then points to the exact
policy and runtime files needed for review.

| Scenario | Use |
| --- | --- |
| [Praxis token quotas](praxis-quotas/README.md) | Inspect providers, preview, apply, and verify shared rolling-day model-token allowances |
| [Streamlit before and after OpenShell](streamlit-security/README.md) | Show credential-free managed inference and a confined filesystem in one short demo |
| [OpenCode PR-candidate queue](opencode-pr-queue/README.md) | Turn public GitHub issues or operator prompts into reviewable patch bundles without giving the agent GitHub write access |
| [Review as a service](../development/review-service.md) | Delegate pull-request review in a restricted sandbox that can read public repositories but cannot push or comment |
| [API key theft](api-key-theft/README.md) | Replay the reported key-stealing agent: the key is findable, and every path to spend it at another provider dies at `connect()` |
| [Document exfiltration](document-exfiltration/README.md) | A malicious downloaded skill tries five legitimate-looking ways to ship a raw document to an attacker bucket; the boundary stops each |
| [Model escalation](model-escalation/README.md) | The same agent image with and without the boundary: one flag spends the key on a premium model in the open; behind the gateway the catalog refuses it before credentials |

Each example names its prerequisites and the evidence it does not claim. Treat
a successful demo as a workflow result, not a substitute for the deployment's
separate qualification tests.
