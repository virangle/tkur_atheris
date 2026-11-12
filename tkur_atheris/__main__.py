"""Run a MODULE:CALLABLE target with upstream Atheris and TKUR stall flags."""
from __future__ import annotations

import importlib
import json
import sys

from . import Fuzz, Setup, backend_info


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--backend-info"]:
        print(json.dumps(backend_info(), indent=2))
        return 0
    if not args or args[0] in ("-h", "--help"):
        print("Usage: tkur_atheris MODULE:CALLABLE [--instrument-all] "
              "[--new-stall SECONDS] [--cov-stall SECONDS] [libFuzzer flags/corpus]")
        print("       tkur_atheris --backend-info")
        return 0
    target = args.pop(0)
    module_name, sep, function_name = target.partition(":")
    if not sep or not module_name or not function_name:
        raise SystemExit("target must be MODULE:CALLABLE")
    instrument_all = "--instrument-all" in args
    args = [arg for arg in args if arg != "--instrument-all"]
    module = importlib.import_module(module_name)
    callback = getattr(module, function_name)
    if not callable(callback):
        raise SystemExit("target is not callable")
    if instrument_all:
        import atheris
        atheris.instrument_all()
    try:
        Setup([target, *args], callback)
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    Fuzz()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
