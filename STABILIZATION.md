# Stage 1 Stabilization / Freeze

This repository is in a consolidation phase after a long period of rapid compiler feature and conformance work.

## Frozen baseline

- integration baseline: `main`
- baseline commit: `6d34a7dbfb4aadb627357844c31d86c3deb1b14c`
- last integrated PR at freeze: #268 (`Test floating atomic RMW under contention`)
- open pull requests at freeze: 0

The baseline already contains the accumulated implementation and tests from the merged feature/correctness sequence through C11 integer, pointer, boolean, float and double atomics.

## Freeze policy

Until Stage 1 stabilization is complete, changes should be limited to:

- compiler correctness fixes with a concrete regression;
- C standard conformance fixes for already-supported language surface;
- SysV AMD64 ABI interoperability fixes;
- preprocessor correctness for already-supported directives/options;
- diagnostics that prevent silent miscompilation or invalid acceptance;
- test determinism, differential tests, fuzz/reducer infrastructure, and sanitizer/static-analysis findings;
- build/CI portability and reproducibility;
- dead-code, duplicate-path, stale-documentation, and test-suite cleanup.

Do not add unrelated language extensions, new targets, a new object-file backend, a new linker, JIT support, a new standard-library family, or broad new C23/C2y features during the freeze.

## Explicitly deferred scope

The following are not Stage 1 release blockers unless an existing supported path accidentally depends on them:

- `long double` / x87 scalar and ABI support;
- non-x86-64 targets;
- non-Linux ABIs;
- a complete hosted libc implementation;
- full C23/C2y language coverage;
- general-purpose aggregate atomics larger than the current lock-free scalar model;
- memory-order-specific weak lowering beyond the current x86-64 strong/seq-cst-or-stronger implementation strategy.

## Stabilization workstreams

### A. Language / semantic conformance

Audit integer constant expressions, conversions, qualifiers, declarators, VLAs/VM types, initializers, `_Generic`, `_Static_assert`, control-flow constraints, and atomic constraints. Prefer GCC/Clang differential cases when behavior is specified and comparable.

### B. SysV AMD64 ABI

Stress direct and indirect calls, GP/SSE exhaustion, variadics, register-save/overflow areas, record classification, hidden sret, narrow integer normalization, floating special values, TLS, and host↔minicc interoperability.

### C. Preprocessor / driver

Audit macro rescanning, placemarkers/token pasting, include search order, line control, predefined macros, dependency generation, option ordering, error recovery, and driver composition. Avoid growing the option surface during freeze.

### D. Atomics / concurrency

Treat the current C11 lock-free 1/2/4/8-byte integer/pointer/float/double surface as a correctness target. Stress CAS retry loops, representation-sensitive compare-exchange, pointer scaling, `_Bool` normalization, volatile atomic objects, single evaluation, and pthread contention.

### E. Toolchain quality

Require full tests under more than one host compiler, run compiler sanitizers, keep generated-object GNU-stack behavior covered, and eliminate flaky or redundant regressions.

## Merge gates

A stabilization PR is eligible to merge only when:

1. the exact head passes the full `make test` suite under GCC and Clang on Ubuntu;
2. sanitizer audit is green, or any narrowly documented sanitizer exception is understood and tracked;
3. no known regression is hidden by weakening/removing an existing test;
4. behavior changes include a focused regression or differential reproducer;
5. README/support claims remain consistent with the implementation;
6. the change does not expand frozen scope unless required to fix an already-supported path.

## Exit criteria

Stage 1 may be considered consolidated when the exact integration head is green under the stabilization CI gates, high-value ABI/conformance differential coverage is in place, sanitizer findings are resolved, the documented supported/deferred boundary is accurate, and there is no known correctness blocker in the supported subset.

After that point, feature development may resume at a lower cadence from the consolidated main baseline.
