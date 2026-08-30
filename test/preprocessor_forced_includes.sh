#!/bin/bash
set -eu

compiler="$(pwd)/minicc"
work="preprocessor-forced-includes-test.$$"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL(preprocessor forced includes): $*" >&2
  exit 1
}

mkdir -p "$work/project" "$work/quote" "$work/user" "$work/system/nested" "$work/after" "$work/custom"

./minicc --help > "$work/help.out"
grep -F -- '-include <file>' "$work/help.out" >/dev/null || fail '--help missing -include'
grep -F -- '-imacros <file>' "$work/help.out" >/dev/null || fail '--help missing -imacros'

# -include contributes both macros and ordinary preprocessed output.
cat > "$work/force.h" <<'SRC'
#define FORCE_VALUE 17
int forced_decl;
SRC
cat > "$work/project/basic.c" <<'SRC'
#if FORCE_VALUE != 17
#error forced include macro missing
#endif
int result = FORCE_VALUE;
SRC
(
  cd "$work"
  "$compiler" -E -include force.h project/basic.c > basic.i
  grep -F 'int forced_decl;' basic.i >/dev/null
  grep -F 'int result = 17;' basic.i >/dev/null
)
echo 'OK(preprocessor forced includes): -include output and macro state'

# -imacros keeps macro effects but discards all ordinary output from the file.
cat > "$work/macros.h" <<'SRC'
#define MACRO_VALUE 23
int must_be_discarded;
SRC
cat > "$work/project/imacros.c" <<'SRC'
#if MACRO_VALUE != 23
#error imacros macro missing
#endif
int result = MACRO_VALUE;
SRC
(
  cd "$work"
  "$compiler" -E -imacros macros.h project/imacros.c > imacros.i
  grep -F 'int result = 23;' imacros.i >/dev/null
  ! grep -F 'must_be_discarded' imacros.i >/dev/null || fail '-imacros leaked ordinary output'
)
echo 'OK(preprocessor forced includes): -imacros discards output'

# All -D/-U actions happen before preincludes, and every -imacros is processed
# before every -include regardless of their interleaving on argv.
cat > "$work/order-macros.h" <<'SRC'
#ifdef CLI_TEMP
#error -U was not applied before -imacros
#endif
#define PRE_STAGE 31
SRC
cat > "$work/order-include-1.h" <<'SRC'
#if PRE_STAGE != 31
#error -imacros did not run before -include
#endif
#define INCLUDE_STAGE 1
SRC
cat > "$work/order-include-2.h" <<'SRC'
#if INCLUDE_STAGE != 1
#error multiple -include files lost order
#endif
#undef INCLUDE_STAGE
#define INCLUDE_STAGE 2
SRC
cat > "$work/project/order.c" <<'SRC'
#if INCLUDE_STAGE != 2
#error include ordering failed
#endif
int result = PRE_STAGE + INCLUDE_STAGE;
SRC
(
  cd "$work"
  "$compiler" -E -include order-include-1.h -DCLI_TEMP=1 \
    -includeorder-include-2.h -UCLI_TEMP -imacrosorder-macros.h \
    project/order.c > order.i
  grep -F 'int result = 31 + 2;' order.i >/dev/null
)
echo 'OK(preprocessor forced includes): D/U, imacros, and include ordering'

# The first search location for a command-line preinclude is the working
# directory, not the primary source directory. If absent there, the normal
# quoted chain continues with -iquote before -I.
cat > "$work/pick.h" <<'SRC'
#define PICK_VALUE 10
SRC
cat > "$work/project/pick.h" <<'SRC'
#error primary source directory must not win command-line -include search
SRC
cat > "$work/quote/next.h" <<'SRC'
#define NEXT_VALUE 20
SRC
cat > "$work/user/next.h" <<'SRC'
#error -I must not beat -iquote for command-line -include
SRC
cat > "$work/project/search.c" <<'SRC'
#if PICK_VALUE != 10 || NEXT_VALUE != 20
#error forced include search order failed
#endif
int result;
SRC
(
  cd "$work"
  "$compiler" -E -I user -iquote quote -include pick.h -include next.h project/search.c > /dev/null
)
rm "$work/pick.h"
if (
  cd "$work"
  "$compiler" -E -include pick.h project/search.c > /dev/null 2> source-dir.err
); then
  fail 'command-line -include incorrectly searched the primary source directory'
fi
echo 'OK(preprocessor forced includes): working-directory and quoted-chain search'

# A resolved preinclude carries its physical path into nested quoted lookup even
# if #line changes the logical file name.
cat > "$work/user/root.h" <<'SRC'
#line 800 "virtual/root.h"
#include "child.h"
#define ROOT_VALUE CHILD_VALUE
SRC
cat > "$work/user/child.h" <<'SRC'
#define CHILD_VALUE 44
SRC
cat > "$work/project/nested.c" <<'SRC'
#if ROOT_VALUE != 44
#error nested physical preinclude lookup failed
#endif
int result = ROOT_VALUE;
SRC
(
  cd "$work"
  "$compiler" -E -I user -include root.h project/nested.c > nested.i
  grep -F 'int result = 44;' nested.i >/dev/null
)
echo 'OK(preprocessor forced includes): nested physical path survives #line'

# System-path preincludes are system dependencies, and that classification is
# transitive through their private quoted children. Both forced files appear in
# -M, while -MM removes the whole system subtree.
cat > "$work/system/sysforce.h" <<'SRC'
#include "nested/private.h"
#define SYSFORCE PRIVATE_VALUE
SRC
cat > "$work/system/nested/private.h" <<'SRC'
#define PRIVATE_VALUE 55
SRC
cat > "$work/project/deps.c" <<'SRC'
int result = SYSFORCE;
SRC
(
  cd "$work"
  "$compiler" -M -isystem system -include sysforce.h project/deps.c > all.mk
  grep -F 'system/sysforce.h' all.mk >/dev/null
  grep -F 'system/nested/private.h' all.mk >/dev/null

  "$compiler" -MM -isystem system -include sysforce.h project/deps.c > user.mk
  ! grep -F 'system/sysforce.h' user.mk >/dev/null
  ! grep -F 'system/nested/private.h' user.mk >/dev/null
)
echo 'OK(preprocessor forced includes): dependency inclusion and system filtering'

# -imacros itself is also a dependency even though its output is suppressed.
(
  cd "$work"
  "$compiler" -M -imacros macros.h -include force.h project/basic.c > forced.mk
  grep -F 'macros.h' forced.mk >/dev/null
  grep -F 'force.h' forced.mk >/dev/null
)
echo 'OK(preprocessor forced includes): imacros dependency tracking'

# -nostdinc disables only the builtin layer. Explicit -idirafter can still
# provide a standard header name to a forced include.
cat > "$work/after/stddef.h" <<'SRC'
#define CUSTOM_STDDEF 66
SRC
cat > "$work/project/nostdinc.c" <<'SRC'
#if CUSTOM_STDDEF != 66
#error explicit after path did not replace disabled builtin
#endif
int result;
SRC
if (
  cd "$work"
  "$compiler" -E -nostdinc -include stddef.h project/nostdinc.c > /dev/null 2> nostdinc.err
); then
  fail '-nostdinc unexpectedly allowed builtin forced stddef.h'
fi
(
  cd "$work"
  "$compiler" -E -nostdinc -idirafter after -include stddef.h project/nostdinc.c > /dev/null
)
echo 'OK(preprocessor forced includes): -nostdinc interaction'

# -MG records missing command-line preinclude names verbatim instead of failing,
# for both -include and -imacros.
cat > "$work/project/missing.c" <<'SRC'
int result;
SRC
(
  cd "$work"
  "$compiler" -MM -MG -include generated/forced.h -imacros generated/macros.h project/missing.c > missing.mk
  grep -F 'generated/forced.h' missing.mk >/dev/null
  grep -F 'generated/macros.h' missing.mk >/dev/null
)
echo 'OK(preprocessor forced includes): -MG missing preincludes'

# Absolute command-line preincludes bypass search paths and still participate in
# dependency tracking.
absolute="$PWD/$work/custom/absolute.h"
cat > "$work/custom/absolute.h" <<'SRC'
#define ABS_FORCE 77
SRC
cat > "$work/project/absolute.c" <<'SRC'
#if ABS_FORCE != 77
#error absolute forced include failed
#endif
int result;
SRC
(
  cd "$work"
  "$compiler" -M -include "$absolute" project/absolute.c > absolute.mk
  grep -F "$absolute" absolute.mk >/dev/null
)
echo 'OK(preprocessor forced includes): absolute forced include'

# Long aliases and attached short forms are accepted.
(
  cd "$work"
  "$compiler" -E --imacros=macros.h --include=force.h project/basic.c > aliases.i
  grep -F 'int forced_decl;' aliases.i >/dev/null
  "$compiler" -E -imacrosmacros.h -includeforce.h project/basic.c > attached.i
  grep -F 'int forced_decl;' attached.i >/dev/null
)
echo 'OK(preprocessor forced includes): aliases and attached forms'

if "$compiler" -include > "$work/include-missing.out" 2> "$work/include-missing.err"; then
  fail 'missing -include argument unexpectedly succeeded'
fi
grep -F "missing argument after '-include'" "$work/include-missing.err" >/dev/null

if "$compiler" -imacros > "$work/imacros-missing.out" 2> "$work/imacros-missing.err"; then
  fail 'missing -imacros argument unexpectedly succeeded'
fi
grep -F "missing argument after '-imacros'" "$work/imacros-missing.err" >/dev/null

echo 'All forced preinclude tests passed!'
