#!/usr/bin/env python3
"""Fail deployment before OpenShell reaches an unusable Landlock kernel."""
import argparse
import ctypes
import os
import platform


LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_CREATE_RULESET_SYSCALL = {
    "x86_64": 444,
    "aarch64": 444,
}


def _landlock_abi():
    if platform.system() != "Linux":
        raise RuntimeError("Landlock preflight requires a Linux host")
    syscall_number = LANDLOCK_CREATE_RULESET_SYSCALL.get(platform.machine())
    if syscall_number is None:
        raise RuntimeError(f"unsupported Landlock preflight architecture: {platform.machine()}")
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.syscall.restype = ctypes.c_long
        result = libc.syscall(
            ctypes.c_long(syscall_number),
            ctypes.c_void_p(None),
            ctypes.c_size_t(0),
            ctypes.c_uint(LANDLOCK_CREATE_RULESET_VERSION),
        )
    except (AttributeError, OSError) as error:
        raise RuntimeError(f"landlock_create_ruleset is unavailable: {error}") from error
    if result < 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))
    return int(result)


def check_landlock(minimum_abi, landlock_abi=_landlock_abi):
    try:
        abi = landlock_abi()
    except (OSError, RuntimeError) as error:
        return False, (
            f"landlock_create_ruleset is unavailable ({error}); "
            "without Landlock, sandbox startup can fail with only ContainerExited"
        )
    if abi < minimum_abi:
        return False, (
            f"host Landlock ABI is {abi}, but ABI {minimum_abi} or later is required; "
            "without it, sandbox startup can fail with only ContainerExited"
        )
    return True, f"host Landlock ABI {abi} meets the required ABI {minimum_abi}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum-abi", type=int, default=3)
    arguments = parser.parse_args()
    passed, message = check_landlock(arguments.minimum_abi)
    if not passed:
        parser.exit(1, f"Landlock preflight failed: {message}\n")
    print(f"Landlock preflight passed: {message}")


if __name__ == "__main__":
    main()
