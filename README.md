# tkur_atheris 0.1.1

Совместимая надстройка Python fuzzing над **Atheris 3.0.0** с общими native
stall timers из [tkur_libfuzzer](https://github.com/virangle/tkur_libfuzzer).
Самостоятельный репозиторий: внешняя Docker-среда или umbrella repository
не нужны. Python bytecode instrumentation, comparisons, custom mutators,
exceptions и API `Setup`/`Fuzz` остаются upstream Atheris.

## Установка из готовых wheel

Для Linux x86_64 / CPython 3.12 скачайте **оба** wheel из Releases:
patched `atheris-3.0.0-...whl` и overlay `tkur_atheris-0.1.1-...whl`.
Устанавливайте их вместе в venv, чтобы pip не подменил patched runtime обычным
PyPI wheel той же версии:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install ./atheris-3.0.0-*.whl ./tkur_atheris-0.1.1-*.whl
python -m tkur_atheris --backend-info
```

Release assets — только `.whl`. Исходный build script и документация находятся
в этом репозитории, а не отдельными downloadable release assets.
Binary wheel содержит license notices для Atheris и статически связанного LLVM.
`--backend-info` должен показать Atheris `3.0.0` и `stall_abi: 1`.
Стандартный PyPI wheel Atheris не содержит TKUR timers: при их включении
надстройка откажется запускать нераспознанный backend.

## Самостоятельная сборка из исходников

Поддерживаемая проверенная среда: Ubuntu 24.04, clang/LLVM 18, Python 3.12.
Нативный `tkur_libfuzzer` собирается **CMake и C++ compiler, без Python**.
Python нужен на следующих шагах именно для сборки Atheris Python extension.

```sh
sudo apt-get update
sudo apt-get install -y git cmake ninja-build build-essential clang-18 llvm-18 \
    binutils python3.12-dev python3.12-venv

# Два самостоятельных sibling checkout, без recursive clone.
git clone https://github.com/virangle/tkur_libfuzzer.git
git clone https://github.com/virangle/tkur_atheris.git

cmake -S tkur_libfuzzer -B tkur_libfuzzer/build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=clang++-18
cmake --build tkur_libfuzzer/build --parallel 2

python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install setuptools==80.9.0 wheel==0.45.1 pybind11==2.13.6
cd tkur_atheris
python build_backend.py
python -m tkur_atheris --backend-info
```

Default archive:
`../tkur_libfuzzer/build/libclang_rt.fuzzer_no_main.a`. Можно явно задать
`python build_backend.py --libfuzzer /absolute/path/libclang_rt.fuzzer_no_main.a`.
Архив должен быть PIC, с TKUR ABI1; используйте соседний `tkur_libfuzzer`,
а не произвольную системную libFuzzer. Его LLVM source pin — 18.1.8.

Build script проверяет SHA256 upstream Atheris sdist, собирает неизмененный
Atheris source через upstream `LIBFUZZER_LIB`, переустанавливает ту же версию
3.0.0 и устанавливает overlay 0.1.1. Для offline source передайте
`--sdist /path/atheris-3.0.0.tar.gz`; проверка SHA256 остается обязательной.
Каждая сборка использует свежий directory, чтобы не переиспользовать stale .so.
Если native archive изменился во время сборки, результат отклоняется.
`build/backend-build.json` сохраняет source/archive hashes и Python version.

`--backend-only` устанавливает только upstream Atheris, например для cache
layer при сборке образа; после него отдельно выполните
`python -m pip install --no-deps --no-build-isolation -e .` и ABI probe.

## Совместимость Setup / Fuzz

Сохраните следующий target как `my_target.py`:

```python
import sys
import tkur_atheris as atheris

@atheris.instrument_func
def TestOneInput(data: bytes):
    if data and data[0] == 84:
        if len(data) > 1 and data[1] == 75:
            data.decode("utf-8", errors="replace")

if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput, custom_mutator=None)
    atheris.Fuzz()
```

```sh
mkdir -p corpus
printf TK > corpus/seed
python my_target.py corpus --new-stall 5 --cov-stall 10 -timeout=3
# Или импортируемый MODULE:CALLABLE:
python -m tkur_atheris my_target:TestOneInput corpus --new-stall=5 --cov-stall=10
# Эквивалентная installed entry point:
tkur_atheris my_target:TestOneInput corpus --cov-stall=5
```

`instrument_imports`, `instrument_func`, `FuzzedDataProvider`, `Mutate`,
`enabled_hooks` и остальные Atheris API forwarded к upstream. `Setup` возвращает
upstream результат; callback/custom_mutator/custom_crossover передаются без
замены. Upstream Atheris3 принимает `internal_libfuzzer`, `custom_mutator`,
`custom_crossover` по keyword. Один Setup/Fuzz на процесс — upstream ограничение.

CLI target должен быть instrumented, например `@atheris.instrument_func`,
либо передайте `--instrument-all`. При включенных timers выбирается
`internal_libfuzzer=True`; preloaded внешние runtime/sanitizer варианты здесь
не заявлены. Без включенных timers обычная upstream external-runtime работа
сохраняется. Backend probe запускается в отдельном коротком Python-процессе,
чтобы ранний dlopen не нарушил ELF weak-symbol resolution custom mutator.
Это только introspection ABI, не wrapper запуска fuzz target.

## Точная семантика

* `--new-stall N` и `--new-stall=N` соответствуют `-new_stall=N`;
  `--cov-stall N` и `--cov-stall=N` соответствуют `-cov_stall=N`.
  Новый CMake native runtime понимает long aliases и непосредственно,
  в том числе при использовании обычного upstream `atheris.Setup`.
* Неотрицательные целые секунды 0..2147483647; `0` отключает timer.
  Проверяются и native spellings; при повторе последнее значение выигрывает.
* Общие native monotonic clock. Оба timer стартуют после начального corpus.
* NEW сбрасывает timer только при **NEW**, не **REDUCE**.
* Cov сбрасывается только при росте total PC coverage (`cov`), не `ft`.
  Features-only NEW может сбросить new-stall, но не cov-stall.
* Любой истекший включенный timer останавливает mutation loop с return 0.
  Driver возвращает в Atheris `GracefulExit` → Python `sys.exit(0)`, поэтому
  запускается `atexit` и сохраняются coverage.py данные.
* Проверка между target executions — это не per-input timeout.
  `-timeout=N` ограничивает отдельный input; crash/timeout сохраняют nonzero
  exit, diagnostics и artifacts.

Нет stdout/stderr parser в реализации, watchdog, process kill, перезапуска
fuzzing или Python coverage approximation. Line/branch coverage.py для отчета
и native `cov`/`ft` — разные метрики.

## Проверки

В разработческой среде реальные subprocess tests проверяют no-growth NEW/cov,
features-only NEW при постоянном cov, рост instrumented Python PCs, REDUCE,
zero disabled, custom-mutator совместимость, crash/input timeout, `atexit` и
coverage.py flush. Нативные long aliases дополнительно проверяются напрямую
через upstream Atheris, без перевода аргументов overlay.
Logs используются только как test oracle; успешная остановка требует native
stall diagnostic, exit 0 и Python cleanup. Аварийный timeout теста — failure.

## Upstream и лицензии

* [Atheris 3.0.0](https://pypi.org/project/atheris/3.0.0/): sdist SHA256
  `1f0929c7bc3040f3fe4102e557718734190cf2d7718bbb8e3ce6d3eb56ef5bb3`.
  Google LLC / Fraunhofer FKIE и upstream contributors, Apache-2.0.
  Atheris version и source implementation не изменяются.
* [tkur_libfuzzer](https://github.com/virangle/tkur_libfuzzer): patched LLVM
  18.1.8, Apache-2.0 WITH LLVM-exception. Исходные лицензии/notices остаются
  в native repository и включены в распространяемый binary wheel Atheris.
* Overlay — Apache-2.0; полный текст в `LICENSE`. Upstream Atheris code
  в overlay не копируется. Upstream license сохраняется в built wheel/source
  и в `build/ATHERIS-LICENSE`.
