# OpenClaw sandbox recipe (experimental)

Follow the [shared setup](common.md), selecting `harness=openclaw` and the dev
profile. The default sandbox name is `openclaw-dev`; `connect.sh` opens a shell.
`--backend` is not supported; it previously printed a value without configuring
anything. Praxis integration is also unsupported: `create.sh --config` fails
before creating a sandbox.

The pinned service command and authentication need qualification before starting
a browser service. A future browser workflow needs both a sandbox-to-RHEL loopback
forward and a workstation tunnel, for example
`ssh -N -L 18789:127.0.0.1:18789 USER@RHEL_HOST`. No browser workflow or retained
service session is qualified. See [AWS validation](../../../bootc/VALIDATION.md).
