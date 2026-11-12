# tkur_atheris — Python fuzzing с общими TKUR stall timers

> Отдельный исходный компонент. Полная Docker-среда, примеры и испытания: [virangle/tkur_fuzzing](https://github.com/virangle/tkur_fuzzing). Команды ниже с путями `components/`, `examples/` и `tests/` выполняются из корня рекурсивно клонированной среды `tkur_fuzzing`.

Самостоятельная сборка: `python3 build_backend.py --libfuzzer /absolute/path/libclang_rt.fuzzer_no_main.a`; архив предоставляет tkur_libfuzzer.


Это тонкая совместимая надстройка, не альтернативный fuzzer. Установленный
`atheris==3.0.0` собирается **из неизмененного upstream source** с PIC-архивом
patched LLVM libFuzzer из соседнего `tkur_libfuzzer`. Python bytecode
instrumentation, comparisons, mutators и exceptions остаются Atheris.

## Сборка (Ubuntu 24.04, Python 3.12)

Нужны `clang-18`, `llvm-18`, `binutils`, `build-essential`, `python3.12-dev`,
venv; pip: `setuptools==80.9.0`, `wheel==0.45.1`, `pybind11==2.13.6`.
Тесты: `pytest==8.4.2`, `coverage==7.10.7`. В предоставленном Docker они есть.
Команды выполняются из `/workspace`:

```sh
python3 components/tkur_libfuzzer/build.py
python3 components/tkur_atheris/build_backend.py
python3 -m tkur_atheris --backend-info
python3 -m pytest tests/python -q
```

С хоста все команды запускаются через `docker exec tkur-dev ...`.
`build_backend.py --libfuzzer /absolute/path/libclang_rt.fuzzer_no_main.a`
позволяет другой путь. `--sdist /path/atheris-3.0.0.tar.gz` дает offline source;
SHA256 проверяется обязательно. Сборка идет в активный Python venv. Повторная
сборка использует свежий source/build directory, чтобы не оставить stale .so.

Скрипт использует upstream `LIBFUZZER_LIB` hook, без LD_PRELOAD и без изменения
upstream Python API. Финальный `--backend-info` проверяет экспортированный
native `TkurLibFuzzerStallAbiVersion()==1`, печатает реальный путь .so и версию.
Стандартное wheel Atheris без patch отклоняется **до** запуска stall timers;
неизвестные libFuzzer flags не могут молча отключить эту функциональность.
`build/backend-build.json` записывает SHA256 source и native archive.
ABI probe выполняется в отдельном коротком Python-процессе: ранний `dlopen`
libFuzzer в основном процессе нарушил бы upstream ELF weak-symbol resolution
для custom mutators. Это introspection протокол, не wrapper fuzzing процесса.
`--backend-only` пропускает только overlay install/probe для Docker cache layers;
после него нужно отдельно установить overlay и запустить `--backend-info`.

## Совместимость Setup / Fuzz

```python
import sys
import tkur_atheris as atheris

@atheris.instrument_func
def TestOneInput(data: bytes):
    if data == b"TKUR":
        pass

atheris.Setup(sys.argv, TestOneInput, custom_mutator=None)
atheris.Fuzz()
```

Другие API, например `instrument_imports`, `FuzzedDataProvider`, `Mutate`,
`enabled_hooks`, forwarded к upstream. `Setup` возвращает upstream результат,
остальные аргументы/kwargs не интерпретируются надстройкой. Upstream Atheris3
принимает `internal_libfuzzer`, `custom_mutator`, `custom_crossover` по keyword.
Один Setup/Fuzz на процесс — ограничение upstream, не добавленная возможность.
При включенных stall timers runtime выбран явно `internal_libfuzzer=True`;
внешние preloaded sanitizer/libFuzzer варианты этой надстройкой не заявлены.
Без включенных таймеров внешний runtime/обычная upstream работа сохраняются.

Пример:

```sh
python3 examples/python/branch_target.py --new-stall 5 --cov-stall 10 corpus
PYTHONPATH=examples/python python3 -m tkur_atheris branch_target:TestOneInput \
    corpus --new-stall=5 --cov-stall=10 -timeout=3
```

CLI принимает `MODULE:CALLABLE`. Target должен быть instrumented, например
`@atheris.instrument_func`, или можно передать `--instrument-all`.

## Точная семантика

* `--new-stall N` → `-new_stall=N`; `--cov-stall N` → `-cov_stall=N`.
* Только неотрицательные целые секунды 0..2147483647; `0` выключает timer.
  Проверяются также native написания; повторный flag: последнее значение.
* Оба timer используют **одни native monotonic clock**; старт после начального
  corpus execution. NEW сбрасывается только при corpus **NEW**, не **REDUCE**.
* Cov сбрасывается только при росте total PC coverage (`cov`), не `ft`.
  Features-only NEW может сбросить new-stall, но не cov-stall.
* Срабатывание любого включенного timer завершает mutation loop с return 0.
  Driver **возвращает** в Atheris `GracefulExit`, где происходит Python
  `sys.exit(0)`, запуск `atexit` и сохранение coverage.py. Это не `_exit(0)`.
* Таймеры проверяются между target executions. Это не per-input timeout:
  зависший target отдельно ограничивается `-timeout=N`, crash/timeout сохраняют
  ненулевой exit и upstream diagnostics/artifacts.

Нет stdout/stderr parser в реализации, polling watchdog, sleep-based kill,
перезапуска процессов или Python coverage approximation. Tests читают реальные
engine diagnostics только для assertions; subprocess timeout — аварийная
граница проваленного теста, а не механизм успешной остановки.

## Проверки

`tests/python` содержит actual Atheris fuzzing: no-growth NEW/cov,
features-only NEW при постоянном cov, настоящее Python PC growth, REDUCE,
0 disabled, custom-mutator compatibility, crash, отдельный input timeout,
atexit и coverage.py flush при native timer shutdown. Fixture использует
детерминированный custom mutator для воспроизводимости, настоящий instrumented
Python loop дает hit-count features, а nested branch — новые PCs.
Отчетное line/branch coverage.py измерение при corpus replay выполняет
`tkur_coverage`, это не `cov`/`ft` libFuzzer.

## Upstream и лицензии

* Atheris 3.0.0: https://pypi.org/project/atheris/3.0.0/ ;
  source tarball SHA256
  `1f0929c7bc3040f3fe4102e557718734190cf2d7718bbb8e3ce6d3eb56ef5bb3`.
  Copyright Google LLC / Fraunhofer FKIE и upstream contributors;
  Apache License 2.0, оригинальный LICENSE сохраняется в wheel/source;
  build script копирует его также в `build/ATHERIS-LICENSE`.
* libFuzzer pin/license/patch находятся в `tkur_libfuzzer`; общий archive,
  не отдельная неточно синхронизированная реализация таймеров.
* Из upstream source код в overlay не копируется. Atheris version не меняется.
  Надстройка также распространяется по Apache-2.0, полный текст сохранен в
  tracked `LICENSE` рядом с package metadata.
