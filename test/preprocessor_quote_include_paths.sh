#!/bin/bash
set -eu

compiler="$(pwd)/minicc"
work="preprocessor-iquote-test.$$"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL(preprocessor -iquote): $*" >&2
  exit 1
}

mkdir -p "$work/project/local" "$work/q1/nested" "$work/q2" "$work/inc" "$work/system"

cat > "$work/project/local/prefer.h" <<'SRC'
#define LOCAL_PREFER 10
SRC
cat > "$work/q1/prefer.h" <<'SRC'
#define LOCAL_PREFER 1000
SRC
cat > "$work/q1/quote-only.h" <<'SRC'
#define QUOTE_ONLY 20
SRC
cat > "$work/q1/priority.h" <<'SRC'
#define QUOTE_PRIORITY 31
SRC
cat > "$work/inc/priority.h" <<'SRC'
#define QUOTE_PRIORITY 99
SRC
cat > "$work/q1/shared.h" <<'SRC'
#define SHARED_VALUE 30
SRC
cat > "$work/q2/shared.h" <<'SRC'
#define SHARED_VALUE 300
SRC
cat > "$work/inc/shared.h" <<'SRC'
#define SHARED_VALUE 40
SRC
cat > "$work/system/system-only.h" <<'SRC'
#define SYSTEM_ONLY 50
SRC
cat > "$work/q1/nested/inner.h" <<'SRC'
#define NESTED_VALUE 60
SRC
cat > "$work/q1/outer.h" <<'SRC'
#line 700 "fake/generated/outer.h"
#include "nested/inner.h"
#define OUTER_VALUE NESTED_VALUE
SRC

cat > "$work/project/main.c" <<'SRC'
#include "local/prefer.h"
#include "quote-only.h"
#include "priority.h"
#include <shared.h>
#include <system-only.h>
#include "outer.h"
int main(void) {
    return (LOCAL_PREFER == 10 && QUOTE_ONLY == 20 && QUOTE_PRIORITY == 31 &&
            SHARED_VALUE == 40 && SYSTEM_ONLY == 50 && OUTER_VALUE == 60)
               ? 0 : 1;
}
SRC

./minicc --help > "$work/help.out"
grep -F -- '-iquote <dir>' "$work/help.out" >/dev/null || fail '--help missing -iquote'

# Quote search order is category-based, not global argv order:
# physical source directory -> -iquote -> -I -> -isystem.  priority.h exists
# in both q1 and inc, and must come from q1 even though -I appears first.
# The angle shared.h ignores -iquote and comes from inc.
(
  cd "$work"
  "$compiler" -Iinc -iquote q1 -iquoteq2 -isystem system project/main.c > main.s
  cc -o main main.s
  ./main
)
echo 'OK(preprocessor -iquote): quote category precedence and angle exclusion'

# Multiple -iquote directories preserve their own order.
cat > "$work/project/order.c" <<'SRC'
#include "shared.h"
#if SHARED_VALUE != 300
#error wrong quote directory order
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -E -iquoteq2 -iquote q1 project/order.c > order.i
)
echo 'OK(preprocessor -iquote): ordered quote-only directories'

# Macro-expanded quoted includes use the same quote-only search phase.
cat > "$work/project/macro.c" <<'SRC'
#define QUOTED_HEADER "quote-only.h"
#include QUOTED_HEADER
#if QUOTE_ONLY != 20
#error macro-expanded quote include did not use -iquote
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -E -iquote q1 project/macro.c > macro.i
  grep -F 'int value;' macro.i >/dev/null
)
echo 'OK(preprocessor -iquote): macro-expanded quoted includes'

# A header that exists only under -iquote is invisible to angle includes.
cat > "$work/project/angle-hidden.c" <<'SRC'
#include <quote-only.h>
int value;
SRC
if (
  cd "$work"
  "$compiler" -E -iquote q1 project/angle-hidden.c > angle-hidden.i 2> angle-hidden.err
); then
  fail 'angle include unexpectedly searched -iquote directory'
fi
grep -F 'cannot include quote-only.h' "$work/angle-hidden.err" >/dev/null

# With -MG, that same unresolved angle include remains the raw generated name;
# the q1/ physical file must still not be consulted.
(
  cd "$work"
  "$compiler" -M -MG -iquote q1 project/angle-hidden.c > angle-mg.mk
  grep -F 'quote-only.h' angle-mg.mk >/dev/null
  ! grep -F 'q1/quote-only.h' angle-mg.mk >/dev/null
)
echo 'OK(preprocessor -iquote): angle exclusion composes with -MG'

# Nested quoted includes from a header found via -iquote resolve relative to the
# physical header location, and #line must not redirect that base.
cat > "$work/project/nested.c" <<'SRC'
#include "outer.h"
#if OUTER_VALUE != 60
#error nested quote lookup failed
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -E -iquote q1 project/nested.c > nested.i
  grep -F 'int value;' nested.i >/dev/null
)
echo 'OK(preprocessor -iquote): physical nested base survives #line'

# Dependencies retain the resolved quote-only path. Since -iquote is a user
# include class, -MM/-MMD keep it. -MP also emits its phony rule.
(
  cd "$work"
  "$compiler" -M -MP -iquote q1 project/nested.c > deps-all.mk
  grep -F 'q1/outer.h' deps-all.mk >/dev/null
  grep -F 'q1/nested/inner.h' deps-all.mk >/dev/null
  grep -Fx 'q1/outer.h:' deps-all.mk >/dev/null

  "$compiler" -MM -iquote q1 project/nested.c > deps-user.mk
  grep -F 'q1/outer.h' deps-user.mk >/dev/null
  grep -F 'q1/nested/inner.h' deps-user.mk >/dev/null

  "$compiler" -S -MMD -iquote q1 -o nested.s project/nested.c
  grep -F 'q1/outer.h' nested.d >/dev/null
  grep -F 'q1/nested/inner.h' nested.d >/dev/null
)
echo 'OK(preprocessor -iquote): dependency generation integration'

# Physical aliasing still deduplicates dependencies and #pragma once through
# quote-only paths, retaining the first encountered spelling.
mkdir -p "$work/once-real" "$work/once-alias"
cat > "$work/once-real/once.h" <<'SRC'
#pragma once
#define ONCE_VALUE 71
SRC
ln -s ../once-real/once.h "$work/once-alias/once-alias.h"
cat > "$work/project/once.c" <<'SRC'
#include "once.h"
#include "once-alias.h"
#if ONCE_VALUE != 71
#error pragma once through -iquote failed
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -M -iquote once-real -iquote once-alias project/once.c > once.mk
  grep -F 'once-real/once.h' once.mk >/dev/null
  ! grep -F 'once-alias/once-alias.h' once.mk >/dev/null
)
echo 'OK(preprocessor -iquote): pragma-once and physical dependency identity'

# If one directory is also registered as -isystem, quote lookup may reach it
# through -iquote first, but dependency classification remains system.  Its
# private quoted subtree must therefore disappear from -MM.
mkdir -p "$work/dual/sub"
cat > "$work/dual/dual.h" <<'SRC'
#include "sub/private.h"
#define DUAL 1
SRC
cat > "$work/dual/sub/private.h" <<'SRC'
#define PRIVATE 1
SRC
cat > "$work/project/dual.c" <<'SRC'
#include "dual.h"
int value = DUAL + PRIVATE;
SRC
(
  cd "$work"
  "$compiler" -M -iquote dual -isystem dual project/dual.c > dual-all.mk
  grep -F 'dual/dual.h' dual-all.mk >/dev/null
  grep -F 'dual/sub/private.h' dual-all.mk >/dev/null

  "$compiler" -MM -iquote dual -isystem dual project/dual.c > dual-user.mk
  ! grep -F 'dual/dual.h' dual-user.mk >/dev/null
  ! grep -F 'dual/sub/private.h' dual-user.mk >/dev/null
)
echo 'OK(preprocessor -iquote): duplicate system directory classification'

# Missing argument is diagnosed, and attached form is accepted above.
if "$compiler" -iquote > "$work/missing.out" 2> "$work/missing.err"; then
  fail 'missing -iquote argument unexpectedly succeeded'
fi
grep -F "missing argument after '-iquote'" "$work/missing.err" >/dev/null

echo 'All quote-only include path tests passed!'
