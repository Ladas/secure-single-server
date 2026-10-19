#!/usr/bin/env python3
"""Safely manage the PR-queue watcher completion marker."""
import os
import fcntl
import stat
import sys
from pathlib import Path


def secure_parent(path):
    parent = path.parent
    resolved_parent = parent.resolve(strict=True)
    if resolved_parent != parent:
        raise SystemExit(f"completion marker parent must be canonical: {parent}")
    if not parent.is_dir():
        raise SystemExit(f"completion marker parent is not a directory: {parent}")
    if parent.stat().st_uid != os.geteuid():
        raise SystemExit(f"completion marker parent is not owned by the current user: {parent}")
    for component in (parent, *parent.parents):
        if component.is_symlink():
            raise SystemExit(f"refusing symlinked completion marker directory: {component}")
        mode = stat.S_IMODE(component.stat().st_mode)
        if mode & 0o022 and not mode & stat.S_ISVTX:
            raise SystemExit(f"refusing unsafe completion marker directory: {component}")


def secure_status(file_status, path):
    if (not stat.S_ISREG(file_status.st_mode) or
            file_status.st_uid != os.geteuid() or
            stat.S_IMODE(file_status.st_mode) & 0o077):
        raise SystemExit(f"refusing unsafe completion marker: {path}")


def marker_path():
    if len(sys.argv) < 3:
        raise SystemExit("usage: completion-marker.py OPERATION PATH [TOKEN]")
    path = Path(sys.argv[2])
    if (not path.is_absolute() or ".." in path.parts or
            not path.name or not path.name.isascii() or
            len(path.name) > 255 or
            not all(character.isalnum() or character in "._-" for character in path.name)):
        raise SystemExit("completion marker path must be absolute and canonical")
    secure_parent(path)
    return path


def open_no_follow(path, flags):
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise SystemExit("platform does not support safe completion marker opening")
    return os.open(path, flags | no_follow | os.O_NONBLOCK)


def create(path):
    descriptor = open_no_follow(path, os.O_RDWR | os.O_CREAT | os.O_EXCL)
    try:
        os.fchmod(descriptor, 0o600)
        secure_status(os.fstat(descriptor), path)
    finally:
        os.close(descriptor)


def write(path, token):
    if len(sys.argv) != 4:
        raise SystemExit("write requires exactly one token")
    encoded_token = (token + "\n").encode()
    if (not token or len(encoded_token) > 257 or
            any(character in token for character in "\r\n")):
        raise SystemExit("invalid completion token")
    descriptor = open_no_follow(path, os.O_WRONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        file_status = os.fstat(descriptor)
        current_status = os.lstat(path)
        if (current_status.st_dev, current_status.st_ino) != (file_status.st_dev, file_status.st_ino):
            raise SystemExit("completion marker changed while it was locked")
        secure_status(file_status, path)
        os.ftruncate(descriptor, 0)
        encoded = (token + "\n").encode()
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise SystemExit("could not write the complete completion marker")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read(path):
    descriptor = open_no_follow(path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        file_status = os.fstat(descriptor)
        secure_status(file_status, path)
        if file_status.st_size > 257:
            raise SystemExit("completion marker is too large")
        chunks = []
        total_size = 0
        while True:
            chunk = os.read(descriptor, 258)
            if not chunk:
                break
            chunks.append(chunk)
            total_size += len(chunk)
            if total_size > 257:
                raise SystemExit("completion marker is too large")
        token = b"".join(chunks).decode()
    finally:
        os.close(descriptor)
    if token.endswith("\n"):
        token = token[:-1]
    encoded_token = token.encode()
    if (not token or len(encoded_token) > 256 or
            any(character in token for character in "\r\n")):
        raise SystemExit("invalid completion token")
    print(token)


def remove(path):
    try:
        descriptor = open_no_follow(path, os.O_RDONLY)
    except FileNotFoundError:
        return
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        file_status = os.fstat(descriptor)
        current_status = os.lstat(path)
        if ((current_status.st_dev, current_status.st_ino) !=
                (file_status.st_dev, file_status.st_ino)):
            raise SystemExit("completion marker changed while it was locked")
        secure_status(current_status, path)
        directory_descriptor = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.unlink(path.name, dir_fd=directory_descriptor)
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        os.close(descriptor)


def validate(path):
    try:
        descriptor = open_no_follow(path, os.O_RDONLY)
    except FileNotFoundError:
        return
    try:
        secure_status(os.fstat(descriptor), path)
    finally:
        os.close(descriptor)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: completion-marker.py OPERATION PATH [TOKEN]")
    operations = {
        "create": create, "write": write, "read": read,
        "remove": remove, "validate": validate,
    }
    operation = sys.argv[1]
    if operation not in operations:
        raise SystemExit(f"unknown completion marker operation: {operation}")
    path = marker_path()
    if operation == "write":
        if len(sys.argv) != 4:
            raise SystemExit("write requires exactly one token")
        write(path, sys.argv[3])
    else:
        operations[operation](path)


if __name__ == "__main__":
    main()
