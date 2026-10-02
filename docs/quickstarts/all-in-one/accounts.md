# Create a user login

The administrator installs services and manages provider credentials. Each
person runs harnesses in a separate ordinary account. Run this once per new
account after installing an [all-in-one profile](README.md). If the account
already exists, skip to login. No provider key is copied to the user.

## 1. Administrator: create the login

In the workstation Bash shell from the installation guide, keep `RHEL_HOST`
and `SSH_OPTIONS` for the intended server. Supply the user's **public** SSH key:

```console
printf 'User public SSH key absolute path: '
IFS= read -r USER_PUBLIC_KEY
scp "${SSH_OPTIONS[@]}" "$USER_PUBLIC_KEY" "$RHEL_HOST:~/praxis-user.pub" &&
ssh -t "${SSH_OPTIONS[@]}" "$RHEL_HOST" 'bash -l'
```

In that administrator SSH session:

```console
cd ~/secure-single-server-deploy
sudo dnf module switch-to -y nodejs:22
sudo dnf install -y nodejs npm git python3 openssh-clients policycoreutils
sudo scripts/common/harness-user --user praxis-user \
  --ssh-public-key "$HOME/praxis-user.pub"
exit
```

The helper creates a private home, authorizes the public key, restores SELinux
labels and installs `praxis-harness`, `praxis-harness-config` and version pins. It grants no
sudo or service-group membership and refuses existing accounts or home paths.
Use a distinct account name and public key for each person. The original
administrator login remains available for service operations.

## 2. User: log in

On the user's workstation, use the matching private key, which stays there.
Enter the server's DNS name or IP, without the administrator username:

```console
{
  printf 'RHEL hostname or IP: '; IFS= read -r USER_HOST
  printf 'Your SSH private-key path: '; IFS= read -r USER_SSH_KEY
}
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$USER_SSH_KEY" "praxis-user@$USER_HOST"
```

Continue with [user setup and usage](users.md) to install the pinned CLIs and
choose Qwen, OpenAI or Anthropic. Remote-gateway users instead follow
[client setup](../remote-gateway/users.md) on their own machines.

For optional sandbox execution, the administrator [installs OpenShell](../openshell-praxis/install.md);
individual sandbox access awaits [OpenShell user enrollment](../openshell-praxis/users.md).
