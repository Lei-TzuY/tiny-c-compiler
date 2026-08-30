#!/bin/bash
set -eu

compiler="$(pwd)/minicc"
work="absolute-include-test.$$"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL(preprocessor absolute include): $*" >&2
  exit 1
}

mkdir -p "$work/project" "$work/headers/nested" "$work/space dir"
root="$(cd "$work" && pwd)"

cat > "$work/headers/nested/inner.h" <<'SRC'
#define ABS_INNER 17
SRC
cat > "$work/headers/outer.h" <<'SRC'
#pragma once
#line 700 "virtual/generated/outer.h"
#include "nested/inner.h"
#define ABS_OUTER (ABS_INNER + 6)
SRC
cat > "$work/space dir/spaced.h" <<'SRC'
#define ABS_SPACED 19
SRC

# Absolute quoted includes bypass the source directory and explicit include
# search classes. Nested quoted includes must still resolve relative to the
# physical absolute header path, even after #line changes its logical filename.
cat > "$work/project/main.c" <<SRC
#include "$root/headers/outer.h"
#include "$root/space dir/spaced.h"
int main(void) { return ABS_OUTER + ABS_SPACED == 42 ? 0 : 1; }
SRC
(
  cd "$work"
  "$compiler" project/main.c > main.s
  cc -o main main.s
  ./main
)
echo 'OK(preprocessor absolute include): compile/run and nested physical lookup'

# Macro-expanded include operands must preserve the same absolute-path behavior.
cat > "$work/project/macro.c" <<SRC
#define ABS_HEADER "$root/headers/outer.h"
#include ABS_HEADER
#if ABS_OUTER != 23
#error macro-expanded absolute include failed
#endif
int value = ABS_OUTER;
SRC
(
  cd "$work"
  "$compiler" -E project/macro.c > macro.i
  grep -F 'int value = (17 + 6);' macro.i >/dev/null
)
echo 'OK(preprocessor absolute include): macro-expanded operand'

# Dependency generation records the resolved absolute physical names. Make
# escaping must protect the space-containing path, while the nested dependency
# remains based on the real outer-header directory rather than the #line name.
(
  cd "$work"
  "$compiler" -M project/main.c > deps.mk
  grep -F "$root/headers/outer.h" deps.mk >/dev/null
  grep -F "$root/headers/nested/inner.h" deps.mk >/dev/null
  escaped_space_root="${root// /\\ }"
  grep -F "$escaped_space_root/space\\ dir/spaced.h" deps.mk >/dev/null
)
echo 'OK(preprocessor absolute include): dependency paths and Make escaping'

# Physical identity remains authoritative across absolute aliases. Including a
# symlink to the same #pragma-once file must neither reprocess it nor duplicate
# its dependency prerequisite.
ln -s "$root/headers/outer.h" "$work/outer-alias.h"
cat > "$work/project/alias.c" <<SRC
#include "$root/headers/outer.h"
#include "$root/outer-alias.h"
int value = ABS_OUTER;
SRC
(
  cd "$work"
  "$compiler" -M project/alias.c > alias.mk
  [ "$(grep -oF "$root/headers/outer.h" alias.mk | wc -l)" -eq 1 ] || \
    fail 'physical absolute dependency was not deduplicated'
  ! grep -F "$root/outer-alias.h" alias.mk >/dev/null || \
    fail 'symlink alias leaked as a duplicate dependency'
)
echo 'OK(preprocessor absolute include): pragma-once physical alias deduplication'

# -MG keeps an unresolved absolute operand verbatim rather than fabricating an
# include-directory prefix.
missing="$root/generated/missing.h"
cat > "$work/project/missing.c" <<SRC
#include "$missing"
int value;
SRC
(
  cd "$work"
  "$compiler" -M -MG project/missing.c > missing.mk
  grep -F "$missing" missing.mk >/dev/null
)
echo 'OK(preprocessor absolute include): -MG preserves unresolved absolute name'

echo 'All absolute include regression tests passed!'
