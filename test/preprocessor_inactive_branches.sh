#!/bin/bash
set -eu

compiler="$(pwd)/minicc"
work="preprocessor-inactive-branches-test.$$"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL(preprocessor inactive branches): $*" >&2
  exit 1
}

mkdir -p "$work"

# Completely inactive subtrees must not evaluate expressions, resolve includes,
# trigger #error, or mutate macro state.
cat > "$work/inactive.c" <<'SRC'
#define KEEP 11
#if 0
#include "definitely-missing.h"
#error inactive error must not fire
#define KEEP 99
#undef KEEP
#if 1 / 0
#error nested inactive #if expression was evaluated
#endif
#endif
#if KEEP != 11
#error inactive macro mutation leaked
#endif
int result = KEEP;
SRC
"$compiler" -E "$work/inactive.c" > "$work/inactive.i"
grep -F 'int result = 11;' "$work/inactive.i" >/dev/null || fail 'inactive branch changed macro state'
echo 'OK(preprocessor inactive branches): inactive directives have no side effects'

# Once a branch in a conditional group has been selected, later #elif
# expressions are not evaluated. This matters for generated configuration
# headers that intentionally leave invalid expressions in unreachable arms.
cat > "$work/elif.c" <<'SRC'
#if 1
#define SELECTED 23
#elif 1 / 0
#error unreachable elif expression was evaluated
#else
#error wrong branch selected
#endif
int result = SELECTED;
SRC
"$compiler" -E "$work/elif.c" > "$work/elif.i"
grep -F 'int result = 23;' "$work/elif.i" >/dev/null || fail '#elif selection regressed'
echo 'OK(preprocessor inactive branches): unreachable #elif is not evaluated'

# An inactive parent also suppresses evaluation of nested #elif expressions.
cat > "$work/nested-elif.c" <<'SRC'
#if 0
#if 0
#error nested inactive branch unexpectedly active
#elif 1 / 0
#error nested inactive elif was evaluated
#endif
#endif
int result = 31;
SRC
"$compiler" -E "$work/nested-elif.c" > "$work/nested-elif.i"
grep -F 'int result = 31;' "$work/nested-elif.i" >/dev/null || fail 'nested inactive conditional changed output'
echo 'OK(preprocessor inactive branches): inactive parents suppress nested #elif evaluation'

# Dependency generation must only record includes that participate in the
# active preprocessing path. -MG makes a missed inactive include especially
# visible because an incorrect implementation would emit it as a prerequisite.
cat > "$work/deps.c" <<'SRC'
#if 0
#include "generated/inactive.h"
#endif
#include "active.h"
int result = ACTIVE_VALUE;
SRC
cat > "$work/active.h" <<'SRC'
#define ACTIVE_VALUE 41
SRC
"$compiler" -M -MG "$work/deps.c" > "$work/deps.mk"
grep -F "$work/active.h" "$work/deps.mk" >/dev/null || fail 'active dependency missing'
! grep -F 'generated/inactive.h' "$work/deps.mk" >/dev/null || fail 'inactive include leaked into dependencies'
echo 'OK(preprocessor inactive branches): dependencies ignore inactive includes'

# Inactive #line directives must not perturb logical source state.
cat > "$work/line.c" <<'SRC'
#if 0
#line 900 "inactive-name.c"
#endif
int observed_line = __LINE__;
const char *observed_file = __FILE__;
SRC
"$compiler" -E "$work/line.c" > "$work/line.i"
grep -F 'int observed_line = 4;' "$work/line.i" >/dev/null || fail 'inactive #line changed __LINE__'
grep -F "const char *observed_file = \"$work/line.c\";" "$work/line.i" >/dev/null || fail 'inactive #line changed __FILE__'
echo 'OK(preprocessor inactive branches): inactive #line does not change logical location'

# #pragma once inside an inactive branch must not mark the physical header.
# Include the header twice and count an ordinary token in preprocess-only output.
cat > "$work/repeat.h" <<'SRC'
#if 0
#pragma once
#endif
int repeated_marker;
SRC
cat > "$work/repeat.c" <<'SRC'
#include "repeat.h"
#include "repeat.h"
SRC
"$compiler" -E "$work/repeat.c" > "$work/repeat.i"
count="$(grep -c '^int repeated_marker;$' "$work/repeat.i" || true)"
[ "$count" = 2 ] || fail "inactive #pragma once suppressed repeated include (count=$count)"
echo 'OK(preprocessor inactive branches): inactive #pragma once is ignored'

echo 'All inactive preprocessor branch tests passed!'
