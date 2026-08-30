#!/bin/bash
set -eu

compiler="$(pwd)/minicc"
work="preprocessor-nostdinc-test.$$"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL(preprocessor -nostdinc): $*" >&2
  exit 1
}

mkdir -p "$work/project" "$work/user" "$work/quote" "$work/system" "$work/after"

./minicc --help > "$work/help.out"
grep -F -- '-nostdinc' "$work/help.out" >/dev/null || fail '--help missing -nostdinc'

# Builtin standard headers remain available by default.
cat > "$work/project/default.c" <<'SRC'
#include <stddef.h>
size_t value;
SRC
(
  cd "$work"
  "$compiler" -E project/default.c > default.i
  grep -F 'typedef unsigned long size_t;' default.i >/dev/null
)
echo 'OK(preprocessor -nostdinc): builtin headers enabled by default'

# -nostdinc disables only builtin standard-header fallback.
if (cd "$work" && "$compiler" -E -nostdinc project/default.c > disabled.out 2> disabled.err); then
  fail 'builtin stddef.h remained visible under -nostdinc'
fi
grep -F 'cannot include stddef.h' "$work/disabled.err" >/dev/null || \
  fail 'missing builtin header diagnostic was not preserved'

if (cd "$work" && "$compiler" -E --no-standard-includes project/default.c > alias.out 2> alias.err); then
  fail '--no-standard-includes did not disable builtin headers'
fi
grep -F 'cannot include stddef.h' "$work/alias.err" >/dev/null || \
  fail '--no-standard-includes diagnostic mismatch'
echo 'OK(preprocessor -nostdinc): builtin fallback disabled and alias supported'

# Current-file relative quoted includes remain available.
cat > "$work/project/local.h" <<'SRC'
#define LOCAL_VALUE 11
SRC
cat > "$work/project/local.c" <<'SRC'
#include "local.h"
#if LOCAL_VALUE != 11
#error local quoted include failed
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -E -nostdinc project/local.c > /dev/null
)
echo 'OK(preprocessor -nostdinc): current-file directory retained'

# Explicit user and quote-only paths remain active regardless of option order.
cat > "$work/user/user.h" <<'SRC'
#define USER_VALUE 21
SRC
cat > "$work/quote/quote.h" <<'SRC'
#define QUOTE_VALUE 22
SRC
cat > "$work/project/explicit-user.c" <<'SRC'
#include <user.h>
#include "quote.h"
#if USER_VALUE != 21 || QUOTE_VALUE != 22
#error explicit user/quote path failed
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -E -nostdinc -I user -iquote quote project/explicit-user.c > /dev/null
  "$compiler" -E -I user -iquote quote -nostdinc project/explicit-user.c > /dev/null
)
echo 'OK(preprocessor -nostdinc): explicit user and quote paths retained'

# Explicit system paths remain searchable and keep system dependency status.
cat > "$work/system/stddef.h" <<'SRC'
#define SYSTEM_STDDEF 31
SRC
cat > "$work/project/system.c" <<'SRC'
#include <stddef.h>
#if SYSTEM_STDDEF != 31
#error explicit system path failed
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -E -nostdinc -isystem system project/system.c > /dev/null
  "$compiler" -M -nostdinc -isystem system project/system.c > system-all.mk
  grep -F 'system/stddef.h' system-all.mk >/dev/null
  "$compiler" -MM -nostdinc -isystem system project/system.c > system-user.mk
  ! grep -F 'system/stddef.h' system-user.mk >/dev/null
)
echo 'OK(preprocessor -nostdinc): explicit system path and dependency class retained'

# With the standard builtin layer disabled, -idirafter can provide a standard
# header name while retaining its final system-header classification.
cat > "$work/after/stddef.h" <<'SRC'
#define AFTER_STDDEF 41
SRC
cat > "$work/project/after.c" <<'SRC'
#include <stddef.h>
#if AFTER_STDDEF != 41
#error idirafter replacement failed
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -E -nostdinc -idirafter after project/after.c > /dev/null
  "$compiler" -M -nostdinc -idirafter after project/after.c > after-all.mk
  grep -F 'after/stddef.h' after-all.mk >/dev/null
  "$compiler" -MM -nostdinc -idirafter after project/after.c > after-user.mk
  ! grep -F 'after/stddef.h' after-user.mk >/dev/null
)
echo 'OK(preprocessor -nostdinc): idirafter remains active after disabled standard layer'

# An explicit -I directory can intentionally provide a standard header name.
cat > "$work/user/stddef.h" <<'SRC'
#define USER_STDDEF 51
SRC
cat > "$work/project/user-stddef.c" <<'SRC'
#include <stddef.h>
#if USER_STDDEF != 51
#error user standard-header replacement failed
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -E -nostdinc -I user project/user-stddef.c > /dev/null
  "$compiler" -MM -nostdinc -I user project/user-stddef.c > user-stddef.mk
  grep -F 'user/stddef.h' user-stddef.mk >/dev/null
)
echo 'OK(preprocessor -nostdinc): explicit user replacement remains a user dependency'

# Absolute includes bypass all search classes and remain usable.
abs_header="$(cd "$work" && pwd)/user/absolute.h"
cat > "$abs_header" <<'SRC'
#define ABS_VALUE 61
SRC
cat > "$work/project/absolute.c" <<SRC
#include "$abs_header"
#if ABS_VALUE != 61
#error absolute include failed
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -E -nostdinc project/absolute.c > /dev/null
)
echo 'OK(preprocessor -nostdinc): absolute includes unaffected'

# -MG sees a formerly builtin header as generated when standard includes are
# disabled, and records the raw header spelling.
cat > "$work/project/generated.c" <<'SRC'
#include <stdint.h>
int value;
SRC
(
  cd "$work"
  "$compiler" -M -MG -nostdinc project/generated.c > generated.mk
  grep -F 'stdint.h' generated.mk >/dev/null
  ! grep -F '/stdint.h' generated.mk >/dev/null

  "$compiler" -MM -MG -nostdinc project/generated.c > generated-user.mk
  grep -F 'stdint.h' generated-user.mk >/dev/null
)
echo 'OK(preprocessor -nostdinc): -MG generated fallback integration'

# Disabling standard header lookup must not disable predefined C macros.
cat > "$work/project/macros.c" <<'SRC'
#ifndef __STDC__
#error __STDC__ disappeared under -nostdinc
#endif
#ifndef __STDC_VERSION__
#error __STDC_VERSION__ disappeared under -nostdinc
#endif
int value;
SRC
(
  cd "$work"
  "$compiler" -E -nostdinc project/macros.c > /dev/null
)
echo 'OK(preprocessor -nostdinc): predefined macros unaffected'

echo 'All -nostdinc tests passed!'
