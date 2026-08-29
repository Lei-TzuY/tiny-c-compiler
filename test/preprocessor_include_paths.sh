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
int main(void) {
    return FIRST + SECOND + THIRD + LOCAL_STDIO - 60;
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

# A quoted local header must win over the compiler's builtin fallback header.
cat > "$work/project/stdio.h" <<'SRC'
#define LOCAL_STDIO 19
SRC

# Angle includes must keep using the builtin/system-style path rather than a
# same-directory quoted-header candidate.
cat > "$work/project/stdlib.h" <<'SRC'
#error local stdlib.h must not satisfy an angle include
SRC

# This distractor proves resolution is relative to project/main.c rather than
# to the process current working directory.
cat > "$work/sub/first.h" <<'SRC'
#error cwd-relative header selected before source-relative header
SRC

(
    cd "$work"
    "$compiler" project/main.c > main.s
    cc -o main main.s
    ./main
)
echo 'OK(preprocessor include path): source-relative and nested quoted includes'

# Preprocess-only mode follows the same path semantics and should expose the
# value from the deeply nested header even when invoked outside the source dir.
(
    cd "$work"
    "$compiler" -E project/main.c > preprocessed.c
    grep -q 'return 11 + 13 + 17 + 19 - 60;' preprocessed.c
)
echo 'OK(preprocessor include path): -E uses source-relative include lookup'

echo 'preprocessor include path tests passed'
