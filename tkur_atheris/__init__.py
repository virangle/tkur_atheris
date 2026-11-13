"""Atheris-compatible frontend, with stall timing owned by patched libFuzzer.

No output parsing, watchdog thread or Python coverage approximation is used.
Other Atheris API names are lazily forwarded to the installed upstream package.
"""
from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
from typing import Sequence

__version__ = "0.1.1"
_MAX_SECONDS = 2**31 - 1
_ALIASES = {"--new-stall": "new_stall", "--cov-stall": "cov_stall"}


def _seconds(value: str, flag: str) -> int:
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError(f"{flag} requires a nonnegative integer number of seconds")
    number = int(value)
    if number > _MAX_SECONDS:
        raise ValueError(f"{flag} exceeds {_MAX_SECONDS} seconds")
    return number


def normalize_args(args: Sequence[str]) -> tuple[list[str], bool]:
    """Translate aliases, preserving libFuzzer's argument order and last-value wins.

    Native spellings are validated too: libFuzzer otherwise accepts malformed
    numbers and silently ignores unknown flags. The caller's list is not changed.
    """
    result: list[str] = []
    values: dict[str, int] = {}
    index = 0
    while index < len(args):
        arg = args[index]
        name, separator, value = arg.partition("=")
        if name in _ALIASES:
            if not separator:
                index += 1
                if index >= len(args):
                    raise ValueError(f"{name} requires a value")
                value = args[index]
            native = _ALIASES[name]
            seconds = _seconds(value, name)
            values[native] = seconds
            result.append(f"-{native}={seconds}")
        elif name in ("-new_stall", "-cov_stall"):
            if not separator:
                raise ValueError(f"{name} requires '=SECONDS'")
            seconds = _seconds(value, name)
            values[name[1:]] = seconds
            result.append(f"{name}={seconds}")
        else:
            result.append(arg)
        index += 1
    return result, any(values.values())


def backend_info() -> dict[str, object]:
    """Inspect actual native ABI in an isolated, short-lived interpreter.

    Loading libFuzzer before upstream loads its custom-mutator DSO would freeze
    ELF weak-symbol resolution and silently disable custom mutators. The probe
    therefore MUST NOT dlopen the core in the fuzzing interpreter. This helper
    process only inspects exported symbols; it never runs/kills a fuzz target or
    parses libFuzzer output. Its JSON is a defined capability-probe protocol.
    """
    program = r'''
import ctypes, importlib.util, json, sys
from importlib.metadata import version
spec = importlib.util.find_spec("atheris.core_with_libfuzzer")
if spec is None or spec.origin is None:
    sys.exit(41)
library = ctypes.CDLL(spec.origin)
try:
    probe = library.TkurLibFuzzerStallAbiVersion
except AttributeError:
    sys.exit(42)
probe.argtypes = []
probe.restype = ctypes.c_int
abi = probe()
if abi != 1:
    sys.exit(43)
print(json.dumps({"atheris_version": version("atheris"), "runtime": spec.origin, "stall_abi": abi}))
'''
    probe = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, timeout=15)
    if probe.returncode != 0:
        raise RuntimeError(
            "Atheris has no compatible TKUR libFuzzer stall ABI; run "
            "build_backend.py from the tkur_atheris source checkout with the patched PIC "
            f"no_main archive first (probe status {probe.returncode})"
        )
    return json.loads(probe.stdout)


def Setup(args, test_one_input, *positional, **kwargs):
    """Forward upstream Setup, adding --new-stall/--cov-stall aliases.

    The upstream callback, custom_mutator, custom_crossover and instrumentation
    APIs are unchanged. Timers require Atheris's built-in patched runtime.
    """
    translated, enabled = normalize_args(args)
    if enabled:
        # Native extension external runtimes can otherwise silently override the
        # inspected built-in runtime. Require an explicit supported selection.
        internal = positional[0] if positional else kwargs.get("internal_libfuzzer")
        if internal is False:
            raise ValueError("TKUR stall timers require internal_libfuzzer=True")
        backend_info()
        if not positional:
            kwargs["internal_libfuzzer"] = True
        elif positional[0] is None:
            positional = (True, *positional[1:])
    if isinstance(args, list):
        args[:] = translated
        translated = args
    return importlib.import_module("atheris").Setup(
        translated, test_one_input, *positional, **kwargs
    )


def Fuzz(*args, **kwargs):
    """Enter upstream Atheris Fuzz; native driver returns into GracefulExit."""
    return importlib.import_module("atheris").Fuzz(*args, **kwargs)


def __getattr__(name):
    return getattr(importlib.import_module("atheris"), name)


def __dir__():
    return sorted(set(globals()) | set(dir(importlib.import_module("atheris"))))
