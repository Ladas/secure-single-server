#!/usr/bin/env python3
"""Extract only regular files and directories from a tar stream on stdin."""
from pathlib import Path, PurePosixPath
import argparse
import sys
import tarfile


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 100_000
COPY_CHUNK_BYTES = 64 * 1024


def member_parts(name):
    path = PurePosixPath(name)
    if path.is_absolute():
        raise ValueError(f"unsafe tar member name: {name}")
    parts = path.parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"unsafe tar member name: {name}")
    return parts


def remove_created_paths(created_paths):
    for path in reversed(created_paths):
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        except FileNotFoundError:
            pass


def ensure_directory(directory, root, created_paths):
    relative_parts = directory.relative_to(root).parts
    for part_count in range(1, len(relative_parts) + 1):
        path = root.joinpath(*relative_parts[:part_count])
        if path.exists():
            if not path.is_dir():
                raise ValueError(f"tar member parent is not a directory: {path}")
            continue
        path.mkdir()
        path.chmod(0o755)
        created_paths.append(path)


def copy_bounded(source, output, member, remaining_file, remaining_total):
    written = 0
    while True:
        chunk = source.read(COPY_CHUNK_BYTES)
        if not chunk:
            break
        written += len(chunk)
        if written > remaining_file:
            raise ValueError(f"tar member exceeds file byte limit: {member.name}")
        if written > remaining_total:
            raise ValueError(f"tar archive exceeds total byte limit: {member.name}")
        output.write(chunk)
    if written != member.size:
        raise ValueError(f"tar member size changed during extraction: {member.name}")
    return written


def extract(stream, destination, max_file_bytes, max_total_bytes, max_members):
    root = destination.resolve(strict=False)
    seen = set()
    created_paths = []
    total_bytes = 0
    file_count = 0
    try:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for member in archive:
                if member.isdir() and member.name in (".", "./"):
                    continue
                parts = member_parts(member.name)
                key = tuple(parts)
                if key in seen:
                    raise ValueError(f"duplicate tar member: {member.name}")
                seen.add(key)
                if len(seen) > max_members:
                    raise ValueError(f"tar archive exceeds member count limit: {member.name}")
                target = root.joinpath(*parts)
                if not target.resolve(strict=False).is_relative_to(root):
                    raise ValueError(f"tar member escapes destination: {member.name}")
                if member.isdir():
                    ensure_directory(target, root, created_paths)
                    continue
                if not member.isfile():
                    raise ValueError(f"unsupported tar member type: {member.name}")
                if member.size < 0 or member.size > max_file_bytes:
                    raise ValueError(f"tar member exceeds file byte limit: {member.name}")
                if total_bytes + member.size > max_total_bytes:
                    raise ValueError(f"tar archive exceeds total byte limit: {member.name}")
                ensure_directory(target.parent, root, created_paths)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(f"could not read tar member: {member.name}")
                output = target.open("xb")
                created_paths.append(target)
                with source, output:
                    total_bytes += copy_bounded(
                        source,
                        output,
                        member,
                        max_file_bytes,
                        max_total_bytes - total_bytes,
                    )
                target.chmod(0o644)
                file_count += 1
    except BaseException:
        remove_created_paths(created_paths)
        raise
    return file_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--max-file-bytes", type=int, default=MAX_FILE_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=MAX_TOTAL_BYTES)
    parser.add_argument("--max-members", type=int, default=MAX_MEMBERS)
    arguments = parser.parse_args()
    if (arguments.max_file_bytes <= 0 or arguments.max_total_bytes <= 0 or
            arguments.max_members <= 0):
        raise SystemExit("limits must be positive")
    destination = arguments.destination
    if not destination.is_dir():
        raise SystemExit(f"destination is not a directory: {destination}")
    file_count = extract(
        sys.stdin.buffer,
        destination,
        arguments.max_file_bytes,
        arguments.max_total_bytes,
        arguments.max_members,
    )
    print(f"extracted {file_count} files")


if __name__ == "__main__":
    main()
