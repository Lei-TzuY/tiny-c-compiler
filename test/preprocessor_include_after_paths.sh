#!/bin/bash
set -eu

compiler="$(pwd)/minicc"
work="preprocessor-idirafter-test.$$"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL(preprocessor -idirafter): $*" >&2
  exit 1
}

mkdir -p "$work/project" "$work/user" "$work/system" \
         "$work/after1/nested" "$work/after2" "$work/dual"

cat > "$work/user/order.h" <<'SRC'
#define ORDER_VALUE 10
SRC
cat > "$work/system/order.h" <<'SRC'
#define ORDER_VALUE 20
SRC
cat > "$work/after1/order.h" <<'SRC'
#define ORDER_VALUE 30
SRC
cat > "$work/after2/order.h" <<'SRC'
#define ORDER_VALUE 40
SRC
cat > "$work/after1/after-only.h" <<'SRC'
#define AFTER_ONLY 51
SRC
cat > "$work/after2/after-only.h" <<'SRC'
#define AFTER_ONLY 52
SRC
cat > "$work/after1/stddef.h" <<'SRC'
#error idirafter must not override builtin stddef.h
SRC
cat > "$work/after1/nested/private.h" <<'SRC'
#define PRIVATE_VALUE 7
SRC
cat > "$work/user/user-child.h" <<'SRC'
#define USER_CHILD_VALUE 8
SRC
cat > "$work/after1/root.h" <<'SRC'
#line 900 "fake/root.h"
#include "nested/private.h"
#include <user-child.h>
#define ROOT_VALUE 9
SRC
cat > "$work/dual/dup.h" <<'SRC'
#define DUP_VALUE 1
SRC
cat > "$work/user/dup.h" <<'SRC'
#define DUP_VALUE 2
SRC

./minicc --help > "$work/help.out"
grep -F -- '-idirafter <dir>' "$work/help.out" >/dev/null || fail '--help missing -idirafter'

# Path-class precedence is independent of argv interleaving: -I beats
# -isystem, and -isystem beats -idirafter.
cat > "$work/project/order.c" <<'SRC'
#include <order.h>
#if ORDER_VALUE != EXPECT
#error wrong include class precedence
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -E -DEXPECT=10 -idirafter after1 -isystem system -I user project/order.c > /dev/null
  "$compiler" -E -DEXPECT=20 -idirafter after1 -isystem system project/order.c > /dev/null
  "$compiler" -E -DEXPECT=30 -idirafter after1 -idirafterafter2 project/order.c > /dev/null
)
echo 'OK(preprocessor -idirafter): class precedence and ordered after paths'

# -idirafter applies to both angle and quote forms.
cat > "$work/project/angle.c" <<'SRC'
#include <after-only.h>
#if AFTER_ONLY != 51
#error angle idirafter lookup failed
#endif
int value;
SRC
cat > "$work/project/quote.c" <<'SRC'
#include "after-only.h"
#if AFTER_ONLY != 51
#error quote idirafter lookup failed
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -E -idirafter after1 project/angle.c > /dev/null
  "$compiler" -E -idirafterafter1 project/quote.c > /dev/null
)
echo 'OK(preprocessor -idirafter): angle and quote lookup'

# Builtin headers are this compiler's standard-system layer and therefore beat
# -idirafter. The poison stddef.h above must never be opened.
cat > "$work/project/builtin.c" <<'SRC'
#include <stddef.h>
size_t value;
SRC
(
  cd "$work"
  "$compiler" -E -idirafter after1 project/builtin.c > builtin.i
  grep -F 'typedef unsigned long size_t;' builtin.i >/dev/null
)
echo 'OK(preprocessor -idirafter): builtin standard headers precede after paths'

# Headers found through -idirafter are system headers. Their relative quoted
# children and even children resolved through a user -I directory remain in
# the transitive system subtree for -MM/-MMD filtering.
cat > "$work/project/deps.c" <<'SRC'
#include <root.h>
int value = ROOT_VALUE + PRIVATE_VALUE + USER_CHILD_VALUE;
SRC
(
  cd "$work"
  "$compiler" -M -I user -idirafter after1 project/deps.c > all.mk
  grep -F 'after1/root.h' all.mk >/dev/null
  grep -F 'after1/nested/private.h' all.mk >/dev/null
  grep -F 'user/user-child.h' all.mk >/dev/null

  "$compiler" -MM -I user -idirafter after1 project/deps.c > user.mk
  ! grep -F 'after1/root.h' user.mk >/dev/null
  ! grep -F 'after1/nested/private.h' user.mk >/dev/null
  ! grep -F 'user/user-child.h' user.mk >/dev/null

  "$compiler" -S -MMD -I user -idirafter after1 -o deps.s project/deps.c
  ! grep -F 'after1/root.h' deps.d >/dev/null
  ! grep -F 'user/user-child.h' deps.d >/dev/null

  "$compiler" -MM -MP -I user -idirafter after1 project/deps.c > phony.mk
  ! grep -F 'after1/root.h:' phony.mk >/dev/null
)
echo 'OK(preprocessor -idirafter): transitive system dependency filtering'

# -MG must search -idirafter before deciding that a header is generated.
cat > "$work/after1/generated.h" <<'SRC'
#define GENERATED_FOUND 1
SRC
cat > "$work/project/generated.c" <<'SRC'
#include <generated.h>
int value;
SRC
(
  cd "$work"
  "$compiler" -M -MG -idirafter after1 project/generated.c > generated.mk
  grep -F 'after1/generated.h' generated.mk >/dev/null
)
echo 'OK(preprocessor -idirafter): -MG searches after paths before fallback'

# If a directory is supplied through both a user/quote class and a system
# class, the early copy is suppressed and the directory is searched only at
# its system position. A distinct -I directory therefore wins here.
cat > "$work/project/duplicate.c" <<'SRC'
#include "dup.h"
#if DUP_VALUE != 2
#error system duplicate was searched too early
#endif
int value;
SRC
cat > "$work/project/duplicate-system.c" <<'SRC'
#include "dup.h"
int value = DUP_VALUE;
SRC
(
  cd "$work"
  "$compiler" -E -iquote dual -isystem dual -I user project/duplicate.c > /dev/null
  "$compiler" -E -iquote dual -idirafter dual -I user project/duplicate.c > /dev/null

  "$compiler" -MM -I dual -idirafter dual project/duplicate-system.c > duplicate.mk
  ! grep -F 'dual/dup.h' duplicate.mk >/dev/null
)
echo 'OK(preprocessor -idirafter): duplicate user/system path suppression'

# Nested quoted lookup remains based on the resolved physical header path,
# even after #line changes the logical filename.
cat > "$work/project/nested.c" <<'SRC'
#include <root.h>
#if PRIVATE_VALUE != 7
#error physical nested lookup failed
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -E -I user -idirafter after1 project/nested.c > /dev/null
)
echo 'OK(preprocessor -idirafter): physical nested base survives #line'

if "$compiler" -idirafter > "$work/missing.out" 2> "$work/missing.err"; then
  fail 'missing -idirafter argument unexpectedly succeeded'
fi
grep -F "missing argument after '-idirafter'" "$work/missing.err" >/dev/null

echo 'All include-after path tests passed!'
