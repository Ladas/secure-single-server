# Create a user login

The administrator installs services and adds provider credentials. Harnesses
run in a separate ordinary account. The smoke runner already creates
`praxis-smoke` for automation; create `praxis-user` for your interactive work.
Use this after [real Qwen setup](../../testing/rhel-real.md) or a standard
all-in-one profile. No provider key is copied to the user.

## 1. Administrator: create the login

On your workstation, choose the AWS all-in-one VM:

```console
TEST_HOST="$ALL_IN_ONE_HOST"
```

Or use the administrator login from a standard deployment quickstart:

```console
TEST_HOST="$RHEL_HOST"
```

Transfer only your public key. These examples use the deployment's `SSH_KEY`
path; each person should supply their own key for their account:

```console
scp -i "$SSH_KEY" "${SSH_KEY}.pub" "$TEST_HOST:~/praxis-user.pub"
ssh -i "$SSH_KEY" "$TEST_HOST"
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
ssh -o ForwardAgent=no -i "$SSH_KEY" "praxis-user@${TEST_HOST#*@}"
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
