#!/bin/bash
set -eu

compiler="$(pwd)/minicc"
work="preprocessor-dump-macros-test.$$"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL(preprocessor -dM): $*" >&2
  exit 1
}

mkdir -p "$work/include"

./minicc --help > "$work/help.out"
grep -F -- '-dM' "$work/help.out" >/dev/null || fail '--help missing -dM'

# -dM replaces ordinary -E output with the final macro table.  Fixed
# predefined macros are included, while dynamic __LINE__/__FILE__ builtins are
# intentionally omitted just like GCC.
cat > "$work/basic.c" <<'SRC'
#define OBJECT 17
#define EMPTY
#define ADD(x, y) ((x) + (y))
#define VARIADIC(tag, ...) tag, __VA_ARGS__
#define GONE 9
#undef GONE
int ordinary_output_must_not_appear = OBJECT;
SRC
./minicc -E -dM "$work/basic.c" > "$work/basic.out"
grep -Fx '#define __STDC__ 1' "$work/basic.out" >/dev/null || fail 'missing __STDC__'
grep -Fx '#define __STDC_VERSION__ 201112L' "$work/basic.out" >/dev/null || fail 'missing __STDC_VERSION__'
grep -Fx '#define __STDC_HOSTED__ 1' "$work/basic.out" >/dev/null || fail 'missing __STDC_HOSTED__'
grep -Fx '#define OBJECT 17' "$work/basic.out" >/dev/null || fail 'missing object-like macro'
grep -Fx '#define EMPTY ' "$work/basic.out" >/dev/null || fail 'missing empty object-like macro'
grep -Fx '#define ADD(x,y) ((x) + (y))' "$work/basic.out" >/dev/null || fail 'function-like macro formatting mismatch'
grep -Fx '#define VARIADIC(tag,...) tag, __VA_ARGS__' "$work/basic.out" >/dev/null || fail 'variadic macro formatting mismatch'
! grep -F '#define GONE ' "$work/basic.out" >/dev/null || fail 'undefined macro leaked into dump'
! grep -F 'ordinary_output_must_not_appear' "$work/basic.out" >/dev/null || fail '-dM did not replace normal -E output'
! grep -F '#define __LINE__' "$work/basic.out" >/dev/null || fail 'dynamic __LINE__ builtin leaked into dump'
! grep -F '#define __FILE__' "$work/basic.out" >/dev/null || fail 'dynamic __FILE__ builtin leaked into dump'
echo 'OK(preprocessor -dM): final macro table and formatting'

# Command-line macro actions are applied before preprocessing and final source
# #undef/#define state is what gets dumped.
cat > "$work/cli.c" <<'SRC'
#define SOURCE_MACRO CLI_VALUE
#undef REMOVE_ME
#define CLI_VALUE 41
SRC
./minicc -E -dM -DCLI_VALUE=1 -DREMOVE_ME=7 -UCLI_VALUE "$work/cli.c" > "$work/cli.out"
grep -Fx '#define CLI_VALUE 41' "$work/cli.out" >/dev/null || fail 'source redefinition did not win'
grep -Fx '#define SOURCE_MACRO CLI_VALUE' "$work/cli.out" >/dev/null || fail 'macro body was not preserved'
! grep -F '#define REMOVE_ME ' "$work/cli.out" >/dev/null || fail 'source #undef did not remove CLI macro'
echo 'OK(preprocessor -dM): CLI and source final-state semantics'

# Includes, -imacros, and -include all contribute to the final macro table,
# while -imacros ordinary output remains irrelevant to -dM.
cat > "$work/imacros.h" <<'SRC'
#define FROM_IMACROS 101
int discarded_imacros_declaration;
SRC
cat > "$work/forced.h" <<'SRC'
#define FROM_INCLUDE 102
SRC
cat > "$work/include/nested.h" <<'SRC'
#define FROM_NESTED 103
SRC
cat > "$work/main.c" <<'SRC'
#include <nested.h>
#define FROM_MAIN 104
SRC
./minicc -E -dM -I "$work/include" -imacros "$work/imacros.h" -include "$work/forced.h" "$work/main.c" > "$work/preincludes.out"
for expected in \
  '#define FROM_IMACROS 101' \
  '#define FROM_INCLUDE 102' \
  '#define FROM_NESTED 103' \
  '#define FROM_MAIN 104'; do
  grep -Fx "$expected" "$work/preincludes.out" >/dev/null || fail "missing preinclude/include macro: $expected"
done
! grep -F 'discarded_imacros_declaration' "$work/preincludes.out" >/dev/null || fail 'ordinary imacros output leaked'
echo 'OK(preprocessor -dM): include and forced-input integration'

# Inactive branches remain side-effect free, including macro definitions.
cat > "$work/inactive.c" <<'SRC'
#define ACTIVE 1
#if 0
#define INACTIVE 2
#undef ACTIVE
#endif
SRC
./minicc -E -dM "$work/inactive.c" > "$work/inactive.out"
grep -Fx '#define ACTIVE 1' "$work/inactive.out" >/dev/null || fail 'active macro missing after inactive branch'
! grep -F '#define INACTIVE ' "$work/inactive.out" >/dev/null || fail 'inactive branch macro leaked into dump'
echo 'OK(preprocessor -dM): inactive branches are side-effect free'

# Standard-header macros are visible after inclusion; -nostdinc itself does not
# remove predefined language macros.
cat > "$work/std.c" <<'SRC'
#include <stdbool.h>
SRC
./minicc -E -dM "$work/std.c" > "$work/std.out"
grep -Fx '#define bool _Bool' "$work/std.out" >/dev/null || fail 'builtin header macro missing'
grep -Fx '#define true 1' "$work/std.out" >/dev/null || fail 'builtin header true macro missing'
printf '' | ./minicc -E -dM -nostdinc - > "$work/nostdinc.out"
grep -Fx '#define __STDC__ 1' "$work/nostdinc.out" >/dev/null || fail '-nostdinc removed predefined macros'
echo 'OK(preprocessor -dM): builtin-header and -nostdinc integration'

# Long aliases and output-file routing.
printf '#define LONG_ALIAS 55\n' > "$work/long.c"
./minicc -E --dump=M "$work/long.c" > "$work/long-equals.out"
grep -Fx '#define LONG_ALIAS 55' "$work/long-equals.out" >/dev/null || fail '--dump=M alias failed'
./minicc -E --dump M "$work/long.c" > "$work/long-separated.out"
grep -Fx '#define LONG_ALIAS 55' "$work/long-separated.out" >/dev/null || fail '--dump M alias failed'
./minicc -E -dM -o "$work/routed.out" "$work/long.c"
grep -Fx '#define LONG_ALIAS 55' "$work/routed.out" >/dev/null || fail '-o routing failed'
echo 'OK(preprocessor -dM): aliases and output routing'

# Definition order is deterministic and follows effective definition time for
# surviving user macros. Redefinition moves the macro to its final position.
cat > "$work/order.c" <<'SRC'
#define FIRST 1
#define SECOND 2
#undef FIRST
#define FIRST 3
SRC
./minicc -E -dM "$work/order.c" > "$work/order.out"
second_line="$(grep -n '^#define SECOND 2$' "$work/order.out" | cut -d: -f1)"
first_line="$(grep -n '^#define FIRST 3$' "$work/order.out" | cut -d: -f1)"
[ "$second_line" -lt "$first_line" ] || fail 'macro dump order is not definition-order deterministic'
echo 'OK(preprocessor -dM): deterministic final definition order'

# -dM is intentionally a preprocessing-only feature in minicc. GCC gives it a
# different compiler-backend meaning without -E, which this compiler does not
# implement.
if ./minicc -dM "$work/long.c" > "$work/no-e.out" 2> "$work/no-e.err"; then
  fail '-dM without -E unexpectedly succeeded'
fi
grep -F "'-dM' requires '-E'" "$work/no-e.err" >/dev/null || fail 'missing -dM/-E diagnostic'
if ./minicc -E --dump X "$work/long.c" > "$work/bad-dump.out" 2> "$work/bad-dump.err"; then
  fail 'unsupported --dump mode unexpectedly succeeded'
fi
grep -F 'only macro dump mode M is supported' "$work/bad-dump.err" >/dev/null || fail 'missing unsupported --dump diagnostic'
if ./minicc -E --dump > "$work/missing-dump.out" 2> "$work/missing-dump.err"; then
  fail '--dump without argument unexpectedly succeeded'
fi
grep -F "missing argument after '--dump'" "$work/missing-dump.err" >/dev/null || fail 'missing --dump argument diagnostic'
echo 'OK(preprocessor -dM): validation diagnostics'

echo 'All macro dump tests passed!'
