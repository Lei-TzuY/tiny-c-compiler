#!/bin/bash
set -eu

compiler="$(pwd)/minicc"
work="include-path-test.$$"
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/project/sub/nested" "$work/sub"

cat > "$work/project/main.c" <<'SRC'
#include "sub/first.h"
#line 400 "virtual/generated.c"
#include "sub/after_line.h"
#include "stdio.h"
#include <stdlib.h>

#define PASS_HEADER(x) x
#define LOCAL_HEADER_NAME "sub/macro.h"
#define INDIRECT_LOCAL_HEADER PASS_HEADER(LOCAL_HEADER_NAME)
#include INDIRECT_LOCAL_HEADER

#define SYSTEM_HEADER_NAME <stdint.h>
#define INDIRECT_SYSTEM_HEADER SYSTEM_HEADER_NAME
#include INDIRECT_SYSTEM_HEADER

int main(void) {
    return FIRST + SECOND + THIRD + LOCAL_STDIO + MACRO_LOCAL +
           (sizeof(uint64_t) == 8 ? 23 : 0) - 106;
}
SRC

cat > "$work/project/sub/first.h" <<'SRC'
#define FIRST 11
#include "nested/second.h"
SRC

cat > "$work/project/sub/nested/second.h" <<'SRC'
#define SECOND 13
SRC

cat > "$work/project/sub/after_line.h" <<'SRC'
#include "../shared.h"
SRC

cat > "$work/project/shared.h" <<'SRC'
#define THIRD 17
SRC

# Macro-expanded quoted includes must still resolve relative to the physical
# source file that contains the directive, after all ordinary macro expansion.
cat > "$work/project/sub/macro.h" <<'SRC'
#define MACRO_LOCAL 23
SRC

# A quoted local header must win over the compiler's builtin fallback header.
cat > "$work/project/stdio.h" <<'SRC'
#define LOCAL_STDIO 19
SRC

# Angle includes must keep using the builtin/system-style path rather than a
# same-directory quoted-header candidate.
cat > "$work/project/stdlib.h" <<'SRC'
#error local stdlib.h must not satisfy an angle include
SRC
cat > "$work/project/stdint.h" <<'SRC'
#error local stdint.h must not satisfy a macro-expanded angle include
SRC

# This distractor proves resolution is relative to project/main.c rather than
# to the process current working directory.
cat > "$work/sub/first.h" <<'SRC'
#error cwd-relative header selected before source-relative header
SRC
cat > "$work/sub/macro.h" <<'SRC'
#error cwd-relative macro-expanded header selected before source-relative header
SRC

(
    cd "$work"
    "$compiler" project/main.c > main.s
    cc -o main main.s
    ./main
)
echo 'OK(preprocessor include path): source-relative, nested, and macro-expanded includes'

# Preprocess-only mode follows the same path semantics and should expose the
# values from nested and macro-expanded headers even when invoked outside the
# source dir. It must also expand the angle-header macro to the builtin stdint.h.
(
    cd "$work"
    "$compiler" -E project/main.c > preprocessed.c
    grep -q 'return 11 + 13 + 17 + 19 + 23 +' preprocessed.c
    grep -q 'sizeof(uint64_t) == 8' preprocessed.c
)
echo 'OK(preprocessor include path): -E preserves macro-expanded include lookup'



# Command-line -I paths are searched in argv order. Angle includes use -I
# before builtin fallback, while quoted includes prefer the physical source
# directory before -I and then retain the historical cwd fallback.
mkdir -p "$work/inc-first/nested" "$work/inc-second" "$work/include-project/local"
cat > "$work/inc-first/ordered.h" <<'SRC'
#define ORDERED_VALUE 31
SRC
cat > "$work/inc-second/ordered.h" <<'SRC'
#define ORDERED_VALUE 99
SRC
cat > "$work/inc-first/angle-only.h" <<'SRC'
#define ANGLE_VALUE 37
SRC
cat > "$work/inc-first/quoted-fallback.h" <<'SRC'
#define QUOTED_FALLBACK 41
SRC
cat > "$work/inc-first/nested/inner.h" <<'SRC'
#define NESTED_VALUE 43
SRC
cat > "$work/inc-first/outer.h" <<'SRC'
#include "nested/inner.h"
#define OUTER_VALUE NESTED_VALUE
SRC
cat > "$work/inc-first/line-base.h" <<'SRC'
#line 700 "fake/generated/header.h"
#include "nested/inner.h"
#define LINE_BASE_VALUE NESTED_VALUE
SRC
cat > "$work/include-project/local/prefer.h" <<'SRC'
#define PREFER_VALUE 47
SRC
cat > "$work/inc-first/prefer.h" <<'SRC'
#define PREFER_VALUE 1000
SRC
cat > "$work/inc-first/stddef.h" <<'SRC'
#define CUSTOM_STDDEF 53
SRC
cat > "$work/include-project/main.c" <<'SRC'
#include "local/prefer.h"
#include "quoted-fallback.h"
#include <ordered.h>
#include <angle-only.h>
#include <outer.h>
#include <line-base.h>
#include <stddef.h>
#ifndef CUSTOM_STDDEF
#error -I header did not override builtin angle header
#endif
int main(void) {
    return PREFER_VALUE + QUOTED_FALLBACK + ORDERED_VALUE + ANGLE_VALUE +
           OUTER_VALUE + LINE_BASE_VALUE + CUSTOM_STDDEF - 295;
}
SRC

(
    cd "$work"
    "$compiler" -I inc-first -Iinc-second include-project/main.c > include-main.s
    cc -o include-main include-main.s
    ./include-main
)
echo 'OK(preprocessor -I): ordering, quote precedence, angle lookup, nested lookup, and #line independence'

# A basename input still has the current working directory as its physical
# source directory, so a local quoted header must beat every -I candidate.
cat > "$work/basename-main.c" <<'SRC'
#include "basename-local.h"
int main(void) { return BASENAME_VALUE == 61 ? 0 : 1; }
SRC
cat > "$work/basename-local.h" <<'SRC'
#define BASENAME_VALUE 61
SRC
cat > "$work/inc-first/basename-local.h" <<'SRC'
#define BASENAME_VALUE 1001
SRC
(
    cd "$work"
    "$compiler" -Iinc-first basename-main.c > basename-main.s
    cc -o basename-main basename-main.s
    ./basename-main
)
echo 'OK(preprocessor -I): basename source keeps local quoted-header precedence'

# Reversing -I order must select the other duplicate header. Use preprocessing
# so the selected macro is directly observable without changing source files.
(
    cd "$work"
    "$compiler" -E -Iinc-second -I inc-first include-project/main.c > include-order.c
    grep -q 'return 47 + 41 + 99 + 37 +' include-order.c
)
echo 'OK(preprocessor -I): argv order is preserved'

# Dependency generation must report resolved physical -I paths and retain
# device/inode deduplication when aliases reach the same pragma-once header.
cat > "$work/inc-first/once-i.h" <<'SRC'
#pragma once
#define ONCE_I_VALUE 59
SRC
mkdir -p "$work/inc-alias"
ln -s ../inc-first/once-i.h "$work/inc-alias/once-i-alias.h"
cat > "$work/include-project/deps.c" <<'SRC'
#include <once-i.h>
#include <once-i-alias.h>
#include <outer.h>
int value = ONCE_I_VALUE + OUTER_VALUE;
SRC
(
    cd "$work"
    "$compiler" -M -Iinc-first -Iinc-alias include-project/deps.c > include-deps.mk
    grep -F 'inc-first/once-i.h' include-deps.mk >/dev/null
    grep -F 'inc-first/outer.h' include-deps.mk >/dev/null
    grep -F 'inc-first/nested/inner.h' include-deps.mk >/dev/null
    [ "$(grep -o 'once-i.h' include-deps.mk | wc -l)" -eq 1 ]
    ! grep -F 'once-i-alias.h' include-deps.mk >/dev/null

    "$compiler" -MD -Iinc-first -Iinc-alias -o include-md.s include-project/deps.c
    test -s include-md.d
    grep -F 'inc-first/once-i.h' include-md.d >/dev/null
    ! grep -F 'once-i-alias.h' include-md.d >/dev/null
)
echo 'OK(preprocessor -I): -M/-MD dependency tracking uses resolved physical headers'

# Builtin fallback still works when no -I candidate exists.
cat > "$work/include-project/builtin.c" <<'SRC'
#include <stdint.h>
int main(void) { return sizeof(uint64_t) == 8 ? 0 : 1; }
SRC
(
    cd "$work"
    "$compiler" -Iinc-first include-project/builtin.c > builtin.s
    cc -o builtin builtin.s
    ./builtin
)
echo 'OK(preprocessor -I): builtin fallback remains available'

# Driver diagnostics for malformed/unsupported -I forms.
if "$compiler" -I > "$work/i-missing.out" 2> "$work/i-missing.err"; then
    echo 'FAIL(preprocessor -I): missing argument unexpectedly succeeded' >&2
    exit 1
fi
grep -F "missing argument after '-I'" "$work/i-missing.err" >/dev/null
if "$compiler" -I- "$work/project/main.c" > "$work/i-dash.out" 2> "$work/i-dash.err"; then
    echo 'FAIL(preprocessor -I): -I- unexpectedly succeeded' >&2
    exit 1
fi
grep -F "'-I-' is not supported" "$work/i-dash.err" >/dev/null

echo 'preprocessor command-line -I tests passed'

echo 'preprocessor include path tests passed'
