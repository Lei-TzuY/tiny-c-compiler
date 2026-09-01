#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
MINICC="$ROOT/minicc"
HOST_CC=${CC:-cc}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

expect_fail() {
    if "$@" >fail.out 2>fail.err; then
        echo "expected failure: $*" >&2
        exit 1
    fi
}

"$MINICC" --help | grep -q -- '-c'
"$MINICC" --help | grep -q -- '--link'

cat > a.c <<'EOF'
int add(int a, int b) { return a + b; }
EOF
cat > b.c <<'EOF'
int add(int, int);
int main(void) { return add(20, 22) == 42 ? 0 : 1; }
EOF

# Preserve the historical single-input default: assembly on stdout, no file.
"$MINICC" a.c > legacy.s
test -s legacy.s
test ! -e a.s

# Multi-input -S creates one basename-derived assembly file per source.
"$MINICC" -S a.c b.c
test -s a.s
test -s b.s
"$HOST_CC" a.s b.s -o from_s
./from_s

# -c accepts multiple C inputs and emits basename .o outputs.
rm -f a.o b.o
"$MINICC" -c a.c b.c
test -s a.o
test -s b.o
"$HOST_CC" a.o b.o -o from_o
./from_o

# Single-input -c honors an explicit output path.
"$MINICC" -c a.c -o custom.o
test -s custom.o

# Raw assembler input can be assembled directly.
cat > asmfunc.s <<'EOF'
  .text
  .globl asm_value
asm_value:
  mov $7, %eax
  ret
  .section .note.GNU-stack,"",@progbits
EOF
"$MINICC" -c asmfunc.s -o asmfunc.o
cat > asm_main.c <<'EOF'
int asm_value(void);
int main(void) { return asm_value() == 7 ? 0 : 1; }
EOF
"$HOST_CC" -c asm_main.c -o asm_main.o
"$HOST_CC" asm_main.o asmfunc.o -o asm_app
./asm_app

# Explicit --link compiles C inputs and links a runnable executable.
"$MINICC" --link a.c b.c -o linked
./linked
rm -f a.out
"$MINICC" --link a.c b.c
./a.out

# Link mode accepts mixed C/assembly/object inputs.
cat > host.c <<'EOF'
int host_value(void) { return 5; }
EOF
"$HOST_CC" -c host.c -o host.o
cat > mixed.c <<'EOF'
int asm_value(void);
int host_value(void);
int main(void) { return asm_value() + host_value() == 12 ? 0 : 1; }
EOF
"$MINICC" --link mixed.c asmfunc.s host.o -o mixed_app
./mixed_app

# -L/-l passthrough works with the host linker driver.
cat > libhelper.c <<'EOF'
int library_value(void) { return 9; }
EOF
"$HOST_CC" -c libhelper.c -o libhelper.o
ar rcs libhelper.a libhelper.o
cat > use_library.c <<'EOF'
int library_value(void);
int main(void) { return library_value() == 9 ? 0 : 1; }
EOF
"$MINICC" --link use_library.c -L. -lhelper -o library_app
./library_app

# Direct archive inputs are forwarded to the host linker in input order.
"$MINICC" --link use_library.c libhelper.a -o archive_app
./archive_app

# Direct shared-object inputs are accepted as link inputs as advertised.
"$HOST_CC" -shared -fPIC libhelper.c -o libhelper.so
"$MINICC" --link use_library.c ./libhelper.so -o shared_app
LD_LIBRARY_PATH=. ./shared_app

# -Wl, arguments are passed through to the host linker driver.
rm -f link.map
"$MINICC" --link a.c b.c -Wl,-Map,link.map -o mapped_app
./mapped_app
test -s link.map
grep -q 'main' link.map

# Independent translation units must not inherit source-defined macros.
cat > macro_a.c <<'EOF'
#define LEAK 1
int macro_a;
EOF
cat > macro_b.c <<'EOF'
#ifdef LEAK
#error source macro leaked between translation units
#endif
int macro_b;
EOF
"$MINICC" -fsyntax-only macro_a.c macro_b.c

# Command-line macros and forced includes are replayed for every TU.
cat > cli_a.c <<'EOF'
#ifndef FLAG
#error FLAG missing
#endif
int cli_a;
EOF
cat > cli_b.c <<'EOF'
#ifndef FLAG
#error FLAG missing
#endif
int cli_b;
EOF
"$MINICC" -DFLAG=1 -fsyntax-only cli_a.c cli_b.c
cat > forced.h <<'EOF'
#define FORCED_VALUE 1
EOF
cat > forced_a.c <<'EOF'
#ifndef FORCED_VALUE
#error forced include missing
#endif
int forced_a;
EOF
cat > forced_b.c <<'EOF'
#ifndef FORCED_VALUE
#error forced include missing
#endif
int forced_b;
EOF
"$MINICC" -include forced.h -fsyntax-only forced_a.c forced_b.c

# Per-TU dependency side effects in multi-file -c use object targets and .d files.
cat > dep.h <<'EOF'
#define DEP_VALUE 3
EOF
cat > dep_a.c <<'EOF'
#include "dep.h"
int dep_a(void) { return DEP_VALUE; }
EOF
cat > dep_b.c <<'EOF'
#include "dep.h"
int dep_b(void) { return DEP_VALUE + 1; }
EOF
"$MINICC" -MD -c dep_a.c dep_b.c
test -s dep_a.d
test -s dep_b.d
grep -q '^dep_a.o: dep_a.c dep.h' dep_a.d
grep -q '^dep_b.o: dep_b.c dep.h' dep_b.d

# Ambiguous or unsafe output combinations are diagnosed.
expect_fail "$MINICC" -c a.c b.c -o both.o
expect_fail "$MINICC" -E a.c b.c
expect_fail "$MINICC" -M a.c b.c
expect_fail "$MINICC" --link -MD a.c b.c
expect_fail "$MINICC" -lhelper a.c
expect_fail "$MINICC" --link a.o -o a.o
printf 'int x;\n' | expect_fail "$MINICC" -c -

# Basename collisions must not silently overwrite one source's result.
mkdir d1 d2
printf 'int x1;\n' > d1/same.c
printf 'int x2;\n' > d2/same.c
expect_fail "$MINICC" -c d1/same.c d2/same.c

# A front-end error must leave an existing object output untouched.
printf 'sentinel-object\n' > keep.o
cp keep.o keep.expected
cat > bad.c <<'EOF'
int broken( { return 1; }
EOF
expect_fail "$MINICC" -c bad.c -o keep.o
cmp keep.expected keep.o

echo 'driver multi-file tests passed'
