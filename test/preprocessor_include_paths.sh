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

echo 'preprocessor include path tests passed'
