# OpenCode PR-candidate queue

Turn a public GitHub issue or an operator prompt into a reviewable patch bundle.
This is issue-or-prompt-to-patch work, not pull-request review. OpenCode makes a
local branch and proposes a diff; a human decides whether to apply it and open a
pull request from a workstation.

```text
issue or prompt
  → bounded OpenCode turn in the pr-queue sandbox
  → task, patch, metadata, and report artifacts
  → human review
  → workstation Git/gh publication
```

The sandbox has no GitHub token and cannot push, create a pull request, comment,
or close an issue. The EC2 or bootc host also never receives the credentials used
to publish code.

## What you get

- One task directory per queued issue or prompt.
- `changes.patch` containing the only proposed code change.
- `metadata.json` recording the repository, base, branch, title, summary, test
  results, risks, and `success` or `failed` status.
- `report.md` written for the human reviewer.
- A clear separation between generation inside the sandbox and publication from
  the workstation.

This example is for one trusted operator and a public repository. It is not
multi-user authorization or proof that generated code is safe.

## Try it

### 1. Check prerequisites

- A reviewed OpenShell + Praxis deployment is already running.
- Praxis has an administrator-approved model and valid provider credentials.
- The target repository is public.
- The operator has enough shared Praxis token quota for the batch.
- The workstation has Git and, for the optional publication step, the GitHub CLI.

Model credentials stay in the host-side Praxis deployment. There is deliberately
no GitHub PAT loading step for the sandbox or queue. For model credential setup,
use the [bootc credential guide](../../quickstarts/bootc/README.md) or the
all-in-one [memory](../../quickstarts/all-in-one/in-memory.md#4-create-provider-secrets)
or [Valkey](../../quickstarts/all-in-one/valkey.md#3-create-provider-secrets)
provider-secret procedures.

### 2. Create the sandbox

On a bootc host:

```console
sudo sss-bootc harness create \
  --profile pr-queue --name opencode-pr-queue \
  --config /usr/share/secure-single-server/configs/openshell-praxis \
  --model administrator-approved-model
```

The explicit `--config` is required. `pr-queue` is integrated with Praxis and
has no standalone direct-provider catalog entry.

On a manual or AWS all-in-one deployment, use the service-owner helper from the
[manual guide](../../quickstarts/openshell-single-server/manual.md#2-set-up-the-service-owner-shell-helper):

```console
os_run "$repo/openshell/harnesses/opencode/create.sh" \
  --profile pr-queue --name opencode-pr-queue \
  --config "$repo/configs/openshell-praxis" \
  --model administrator-approved-model
```

### 3. Queue work

On a bootc host, queue one or more public issues:

```console
sudo sss-bootc harness queue \
  --name opencode-pr-queue \
  --repo OWNER/REPOSITORY \
  --issue 123 --issue 124 \
  --message "Keep the change focused and include documentation" \
  --timeout 7200
```

On a manual or AWS all-in-one deployment, use the queue runner directly:

```console
os_run "$repo/openshell/harnesses/opencode/pr-queue/queue.sh" \
  --name opencode-pr-queue \
  --repo OWNER/REPOSITORY \
  --issue 123 --issue 124 \
  --message "Keep the change focused and include documentation" \
  --timeout 7200
```

To queue the included prompt on a bootc host, first create a readable task file
outside the image:

```console
sudo tee /var/tmp/opencode-pr-queue-demo-task.md >/dev/null <<'EOF'
Create a new file named OPENCODE_DEMO.md at the repository root.

The file must contain exactly this line:
OpenCode PR-candidate queue demo succeeded.

Do not modify any other file. If the repository has no tests, record that no
tests are applicable.
EOF
sudo sss-bootc harness queue \
  --name opencode-pr-queue \
  --repo octocat/Hello-World \
  --prompt-file /var/tmp/opencode-pr-queue-demo-task.md \
  --timeout 900
```

On a manual or AWS deployment, use the prompt checked out with the repository:

```console
os_run "$repo/openshell/harnesses/opencode/pr-queue/queue.sh" \
  --name opencode-pr-queue \
  --repo octocat/Hello-World \
  --prompt-file "$repo/docs/examples/opencode-pr-queue/demo-task.md" \
  --timeout 900
```

Tasks run sequentially in the named sandbox. Each turn, including SSH setup and
artifact checks, is bounded from 60 seconds through four hours; the default is
one hour.

For a live demonstration, run the command directly and let the JSON events
stream. For a longer batch that must survive an SSH disconnect, start it in
tmux:

```console
tmux new-session -s opencode-pr-queue
# run the queue command above
```

Detach with `Ctrl-b` and then `d`. Reconnect with:

```console
tmux attach-session -t opencode-pr-queue
```

tmux is optional. The queue itself does not require it.

### 4. Collect the artifacts

On the deployed host:

```console
sudo sss-bootc harness collect \
  --name opencode-pr-queue \
  --dest /var/tmp/opencode-pr-queue-artifacts
```

The collector uses the existing OpenShell SSH channel. Its safe extractor accepts
only regular files and directories, so malformed sandbox output cannot traverse
outside the destination. A missing or empty required artifact is a failed task,
not an empty success. A failed task may omit `changes.patch` when `report.md`
explains the failure.

Copy the bundle to the workstation when ready:

```console
scp -r ec2-user@SERVER:/var/tmp/opencode-pr-queue-artifacts ./
```

### 5. Review and publish

Read `report.md`, inspect `changes.patch`, and check `metadata.json`. Then apply
exactly one accepted patch in a clean target checkout:

```console
base_ref="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["base_ref"])' \
  ../opencode-pr-queue-artifacts/issue-123-*/metadata.json)"
base_commit="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["base_commit"])' \
  ../opencode-pr-queue-artifacts/issue-123-*/metadata.json)"
git fetch origin "$base_ref"
if [[ "$(git rev-parse FETCH_HEAD)" == "$base_commit" ]]; then
  git switch -c agent/issue-123 "$base_commit"
else
  echo "Collected base no longer matches ${base_ref}" >&2
  false
fi
git apply --3way ../opencode-pr-queue-artifacts/issue-123-*/changes.patch
git diff --check
```

Run the repository's tests and inspect the complete diff. If the result is
acceptable, commit it with an appropriate message and attribution, then publish:

```console
git push -u origin agent/issue-123
gh pr create --draft \
  --title "Proposed fix for issue 123" \
  --body-file ../opencode-pr-queue-artifacts/issue-123-*/report.md
```

With an SSH remote, `git push` uses the workstation SSH key; with HTTPS, it can
use the workstation credential manager. `gh pr create` uses the GitHub CLI's
workstation authentication. If `gh` is absent, install it on the workstation or
push the branch and open the draft PR in the GitHub web UI. Do not move a
write-capable PAT to the server to work around a missing local CLI.

The proposed title and summary in `metadata.json` are suggestions, not approved
content. Nothing is published until the human reviewer takes these workstation
actions.

## Check token capacity

Praxis token quotas count input, output, cached, and repeated prompt/history
tokens. A 30-task batch at roughly 30,000 total tokens per turn is already near
the shipped 1,000,000-token rolling-day safety default before overhead, retries,
or additional operators are considered.

From the deployed checkout:

```console
sudo scripts/common/quota-status
sudo scripts/common/quota-set --list
```

Preview and apply a larger OpenAI rolling-day capacity:

```console
sudo scripts/common/quota-set --provider openai --capacity 10000000
sudo scripts/common/quota-set --provider openai --capacity 10000000 --apply
```

Stop active tasks before applying a changed capacity. Apply restarts Praxis:
memory-quota usage resets, while Valkey ledger usage survives. On a managed
Valkey gateway, an administrator can also clear selected provider usage for
testing:

```console
sudo scripts/common/quota-reset --list
sudo scripts/common/quota-reset --provider openai --apply
```

These are shared allowances, not per-user budgets or USD spend caps. See the
[token quota guide](../../quickstarts/common/token-quotas.md) for backend
persistence, metrics, and reset limitations.

## Security boundary

| Binary | Destination | Access |
| --- | --- | --- |
| `opencode`, `node-26` | Praxis gateway | Model calls only |
| `node-26`, `git` | `api.github.com` | REST, read-only |
| `git` | `github.com:443` | Git Smart HTTP clone/fetch only |

The `pr-queue` profile allows no npm, documentation, cloud-provider, or other
network destination. Git push uses `git-receive-pack`, which is denied by the
Layer 7 rules. OpenShell records allowed and denied attempts in its audit log.

Queue turns run OpenCode with `--pure --auto` and a closed stdin channel.
`--pure` avoids external plugin discovery, `--auto` prevents a non-interactive
turn from waiting for OpenCode's own tool prompt, and closing stdin prevents
`opencode run` from waiting for terminal input. These choices do not expand the
boundary: OpenShell still enforces the filesystem, process, and network policy.

## Where this example lives

| Purpose | Path |
| --- | --- |
| This user-facing runbook | `docs/examples/opencode-pr-queue/README.md` |
| Ready-to-run demo prompt | [demo-task.md](demo-task.md) |
| Sandbox policy | [`configs/openshell-praxis/profiles/pr-queue/policy.yaml`](../../../configs/openshell-praxis/profiles/pr-queue/policy.yaml) |
| OpenCode model/provider template | [`configs/openshell-praxis/pr-queue/harness-provider.json.in`](../../../configs/openshell-praxis/pr-queue/harness-provider.json.in) |
| Queue runner | [`openshell/harnesses/opencode/pr-queue/queue.sh`](../../../openshell/harnesses/opencode/pr-queue/queue.sh) |
| Artifact collector | [`openshell/harnesses/opencode/pr-queue/collect.sh`](../../../openshell/harnesses/opencode/pr-queue/collect.sh) |
| Shared metadata validation | [`openshell/harnesses/opencode/pr-queue/lib.sh`](../../../openshell/harnesses/opencode/pr-queue/lib.sh) |
| Agent instructions and artifact contract | [`openshell/harnesses/opencode/pr-queue/instructions.md`](../../../openshell/harnesses/opencode/pr-queue/instructions.md) |
| Contracts and tests | [`openshell/tests/pr-queue.py`](../../../openshell/tests/pr-queue.py) |

Executable runtime code stays under `openshell/` and deployment configuration
stays under `configs/`. This page is the single entry point; the source map
above exists for review and audit, not as required reading before the first run.

## Limits and factory evolution

- Public repositories only. A GitHub token in the sandbox would create a new
  credential surface and is outside this example.
- Unauthenticated GitHub API access is rate-limited; the agent instructions tell
  OpenCode to fetch issue metadata once.
- One invocation runs sequentially in one sandbox. Split large batches into
  multiple invocations.
- A patch, passing test output, or model completion is not proof that a change is
  correct or secure. Human review remains mandatory.

A “dark factory” can preserve this boundary by separating queue intake, isolated
bounded workers, a human review gate, and a workstation or CI promoter that alone
holds publication credentials. A durable implementation would replace tmux with
a `systemd --user` worker and a SQLite or PostgreSQL job store, add concurrency
and retry controls, and retain audit logs and artifacts for every accepted or
rejected job. GitHub labels or webhooks can feed intake without granting the
sandbox write access. That evolution is not included in this example.
