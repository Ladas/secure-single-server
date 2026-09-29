# Create a user login

The administrator installs services and adds provider credentials. Harnesses
run in a separate ordinary account. The smoke runner already creates
`praxis-smoke` for automation; use `praxis-user` for your interactive work.
If you created it during [AWS setup](../../testing/aws.md#5-create-the-all-in-one-user-login),
skip to [login](#2-user-log-in). Otherwise use the steps below after
[real Qwen setup](../../testing/rhel-real.md) or a standard all-in-one profile.
No provider key is copied to the user.

## 1. Administrator: create the login

On your workstation, select the all-in-one VM using
`aws_test_verify all-in-one-gpu` or `aws_test_verify all-in-one-cpu` from the
[AWS guide](../../testing/aws.md#4-select-one-vm-for-testing). For a standard
quickstart, keep its `RHEL_HOST` and `SSH_KEY` instead.

Transfer only your public key. These examples use the deployment's `SSH_KEY`
path; each person should supply their own key for their account:

```console
scp -i "$SSH_KEY" "${SSH_KEY}.pub" "$RHEL_HOST:~/praxis-user.pub"
ssh -i "$SSH_KEY" "$RHEL_HOST"
```

In the administrator session:

```console
cd ~/secure-single-server-deploy
sudo dnf module switch-to -y nodejs:22
sudo dnf install -y nodejs npm git python3 openssh-clients policycoreutils
sudo scripts/common/harness-user --user praxis-user \
  --ssh-public-key "$HOME/praxis-user.pub"
exit
```

The helper creates a private home, installs the SSH key, restores SELinux
labels and makes the client launcher/version pins available. It grants no
sudo or service-group membership and refuses existing accounts or home paths.
Run it once per new account. Each person should supply their own public key.
The original administrator login remains available for service operations.

## 2. User: log in

On your workstation:

```console
ssh -o ForwardAgent=no -i "$SSH_KEY" "praxis-user@${RHEL_HOST#*@}"
```

Continue with [user setup and usage](users.md) to install the pinned CLIs and
choose Qwen, OpenAI or Anthropic. For acceptance, follow the
[manual file/test task](../../testing/harnesses.md). Remote-gateway clients use
the workstation HTTPS/JWT flow from that guide.

## 3. Optional OpenShell

The same ordinary account can use the experimental local OpenShell client.
The administrator still owns installation and service maintenance; the
user does not become `openshell-svc` or receive its Podman socket or files.
Follow [manual OpenShell testing](../../testing/openshell-manual.md) for the separate
installation, registration and sandbox commands.
