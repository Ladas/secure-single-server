# Postmortem: the review turn that waited for EOF

Date: 2026-10-14. Branch: `feature/review-service`. Scope: the first
end-to-end `pr-55` review run on the AWS bootc host. Workflow context:
[review as a service](review-service.md).

## Summary

The first full review run (`review.sh --pr 55`) sat silent for an hour —
no clone, no gateway traffic, no report — then "finished" by timeout, after
which the review secretly started running headless, cloned the repository,
fetched the PR metadata, and ended without writing a report.

The root cause is one behavior of the OpenCode CLI: `opencode run` drains
piped stdin to EOF before submitting its prompt. Over `harness_ssh` (no PTY)
the turn's stdin is the SSH channel, and that channel never EOFs while the
operator's terminal holds it open. The turn parked in the event loop before
creating a session and waited for an EOF that could only arrive by accident.

## Timeline

| Time (UTC) | Event |
| ---------- | ----- |
| 21:15 | `review.sh --pr 55 --timeout 3600` starts; workspace and task pushed |
| 21:16 | OpenCode startup completes (known noise only); no session created |
| 21:22 | Operator's manual test via `connect_bash` (PTY) succeeds — misleading |
| 21:43 | A/B stdin experiment via `harness_ssh`: EOF finishes in 6 s, held-open pipe hangs |
| 22:15 | Timeout kills the local ssh; the channel close delivers the EOF; the parked turn starts |
| later | Turn found gone: clone and metadata present in `~/review`, `~/reports` empty |

## What the hang looked like

Three observations, each pointing away from the obvious suspects:

- The OpenCode log showed a complete startup (the `models.dev` ERROR and the
  npm WARN ~70 s in — both known noise) and then nothing: no
  `created id=ses_...` session line, no `loop`, no `stream`.
- The Praxis gateway journal had no entries at all — not 429s, nothing. No
  request had ever been attempted, which ruled out quota exhaustion.
- The process was alive with seven threads, all idle: `epoll_wait` and
  futexes, zero open sockets, no lock contention. Something was waiting for
  an event that never came.

## Diagnosis

The sandbox's own `/proc` is policy-locked — even same-uid reads of
`/proc/<pid>/syscall` are denied, good hardening but inconvenient forensics —
so the evidence came from the host side as root, using the container's
host-side PID:

- `sudo cat /proc/<pid>/syscall` — `epoll_pwait2`: the event loop, idle
- `sudo ls -l /proc/<pid>/fd` — fd 0 a pipe; no sockets anywhere; SQLite
  storage open but idle
- Pipe ownership — the write end of fd 0 held by `openshell-sandbox`, the
  supervisor forwarding the SSH channel
- `sudo cat /proc/<pid>/fdinfo/<epoll>` — fd 0 registered with `EPOLLIN`:
  the process was kernel-level waiting on stdin

The confirmation was an A/B experiment through `harness_ssh` itself — same
command, same directory, one variable:

```bash
# B: stdin closed — completed in 6 seconds
harness_ssh "$name" 'cd ~/review && opencode run --format json "respond with OK"' </dev/null

# A: stdin an open pipe with no data — hung until killed
sleep 150 | harness_ssh "$name" 'cd ~/review && opencode run --format json "respond with OK"'
```

Control B answered "OK" in six seconds. Repro A hung until its timeout.

## Root cause

`opencode run` supports piped prompts (`echo message | opencode run`) and
drains stdin to EOF before submitting — even when the prompt is already in
argv. When stdin is a TTY it skips the read, which is why every interactive
test passed: `connect_bash` allocates a PTY, so the operator's manual
"respond with OK" worked and pointed away from the transport. `review.sh`
launches the turn over SSH without a PTY, so the CLI saw a pipe, read it,
and waited.

## The twist: the zombie was the smoking gun

The operational lore said "Ctrl-C on `review.sh` leaves a zombie opencode
that keeps consuming quota." The forensic picture reframes it: killing the
SSH connection closes the channel, which delivers exactly the EOF a parked
turn is waiting for. The disconnect does not merely fail to kill the turn —
sometimes it is what starts it. That is what happened at 22:15: the timeout
tore down the connection, the EOF woke the turn, and the review ran headless
until it ended with an empty `~/reports`.

Why the zombie ended without a report is unknown. Its stdout channel was
gone with the ssh connection, and the report contract in
`openshell/harnesses/opencode/review-agents.md` says even a failed turn
writes `~/reports/pr-N.md` — none appeared. That question stays open.

## The fix

One redirect inside the remote command, so both execution branches (with and
without `timeout`) are covered and the file-push calls keep their stdin:

```bash
review_cmd='cd ~/review && opencode run --format json "$(cat task.md)" </dev/null'
```

The regression test (`test_review_turn_stdin_reaches_eof` in
`tests/openshell-praxis/offline.py`) closes the blind spot that let this
ship: the existing fake ssh recorded command lines but never forwarded
stdin. The new fake executes the remote command with stdin passed through,
like real ssh, and the fake `opencode` drains stdin to EOF — the unfixed
script hangs the test; the fixed one passes in under a second.

## Lessons

- A test shim must be faithful on the axis the bug lives on. Recording
  arguments is not enough when the failure is about data flow.
- An empty gateway journal is evidence: no 429 lines means no requests,
  which excludes quota before anyone restarts anything.
- Hardened sandboxes block same-uid `/proc` forensics, but the host side of
  the container PID still answers everything as root.
- "Keeps running after disconnect" and "started because of the disconnect"
  are the same mechanism wearing different hats.
