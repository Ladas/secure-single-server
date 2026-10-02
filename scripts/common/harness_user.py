#!/usr/bin/env python3
"""Create a new ordinary SSH account for manual harness testing on RHEL."""
import argparse
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HOME_ROOT = Path("/home")
BIN_DIR = Path("/usr/local/bin")
DATA_DIR = Path("/usr/local/share/praxis")


def run(*command):
    subprocess.run(command, check=True)


def public_key(path):
    value = path.read_text().strip()
    fields = value.split()
    if (len(value.splitlines()) != 1 or len(fields) < 2 or
            fields[0] not in ("ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256",
                              "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
                              "sk-ssh-ed25519@openssh.com", "sk-ecdsa-sha2-nistp256@openssh.com")):
        raise ValueError("supply one plain SSH public key, without authorized_keys options")
    result = subprocess.run(["ssh-keygen", "-l", "-f", str(path)], capture_output=True)
    if result.returncode:
        raise ValueError("invalid SSH public key")
    return value + "\n"


def create(user, key_file):
    if (not re.fullmatch(r"[a-z][a-z0-9_-]{0,30}", user) or
            user in ("root", "praxis-svc", "openshell-svc", "praxis-smoke")):
        raise ValueError("choose a new personal account name, separate from service/smoke accounts")
    try:
        pwd.getpwnam(user)
    except KeyError:
        pass
    else:
        raise ValueError(f"account {user} already exists; no account or key was changed")
    home = HOME_ROOT / user
    if home.exists() or home.is_symlink():
        raise ValueError(f"home already exists: {home}; no account was created")
    key = public_key(key_file)
    launcher = (ROOT / "scripts/common/harness.py").read_bytes()
    configure = (ROOT / 'scripts/common/harness_config.py').read_bytes()
    versions = (ROOT / "configs/common/harness-versions.json").read_bytes()
    run("useradd", "--create-home", "--user-group", "--home-dir", str(home),
        "--shell", "/bin/bash", user)
    account = pwd.getpwnam(user)
    if (account.pw_uid < 1000 or account.pw_gid == 0 or account.pw_dir != str(home) or
            set(os.getgrouplist(user, account.pw_gid)) != {account.pw_gid}):
        raise ValueError("new account has unexpected UID or groups; inspect it before enabling login")
    home.chmod(0o700)
    # Only public client tooling is shared; never copy the deployment bundle,
    # its material directory, provider secrets or the OpenShell owner's state.
    for directory, name, content, mode in (
            (BIN_DIR, "praxis-harness", launcher, 0o755),
            (BIN_DIR, 'praxis-harness-config', configure, 0o755),
            (DATA_DIR, "harness-versions.json", versions, 0o644)):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o755)
        target = directory / name
        target.write_bytes(content)
        target.chmod(mode)
    ssh = home / ".ssh"
    ssh.mkdir(mode=0o700)
    os.chown(ssh, account.pw_uid, account.pw_gid)
    authorized = ssh / "authorized_keys"
    fd = os.open(authorized, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(key)
    os.chown(authorized, account.pw_uid, account.pw_gid)
    run("restorecon", "-RF", str(home))
    print(f"Created {user}: SSH public key installed; no sudo or service-group membership granted.")
    print("Log in as this user and install the pinned CLIs from /usr/local/share/praxis/harness-versions.json.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True)
    parser.add_argument("--ssh-public-key", required=True, type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run as the administrator with sudo")
    if not sys.platform.startswith("linux"):
        parser.error("this helper creates accounts on Linux hosts only")
    for command in ("useradd", "ssh-keygen", "restorecon"):
        if not shutil.which(command):
            parser.error(f"required host command missing: {command}")
    try:
        create(args.user, args.ssh_public_key)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
