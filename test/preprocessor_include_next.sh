#!/bin/bash
set -eu

compiler="$(pwd)/minicc"
work="preprocessor-include-next-test.$$"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL(preprocessor include_next): $*" >&2
  exit 1
}

mkdir -p "$work/project" "$work/q1" "$work/q2" "$work/qtrap" \
         "$work/i1" "$work/i2" "$work/system" "$work/after1" \
         "$work/after2" "$work/abs" "$work/dup" "$work/userdep" \
         "$work/sysdep"

# A header found beside the physical source continues after that source
# directory, so -iquote is the first include_next class searched.
cat > "$work/project/wrapper.h" <<'SRC'
#define SOURCE_WRAPPER 1
#include_next "target.h"
SRC
cat > "$work/project/target.h" <<'SRC'
#error include_next must skip the current source directory
SRC
cat > "$work/q1/target.h" <<'SRC'
#define QUOTE_TARGET 2
SRC
cat > "$work/project/source-local.c" <<'SRC'
#include "wrapper.h"
#if SOURCE_WRAPPER != 1 || QUOTE_TARGET != 2
#error source-local include_next chain failed
#endif
int source_local_ok;
SRC
"$compiler" -E -iquote "$work/q1" "$work/project/source-local.c" > "$work/source-local.i"
grep -F 'int source_local_ok;' "$work/source-local.i" >/dev/null
echo 'OK(preprocessor include_next): source-local origin continues at -iquote'

# Multiple quote-only directories retain their left-to-right order.
cat > "$work/q1/quote-layer.h" <<'SRC'
#define QUOTE_ONE 1
#include_next <quote-layer.h>
SRC
cat > "$work/q2/quote-layer.h" <<'SRC'
#define QUOTE_TWO 2
SRC
cat > "$work/project/quote-chain.c" <<'SRC'
#include "quote-layer.h"
#if QUOTE_ONE != 1 || QUOTE_TWO != 2
#error quote include_next chain failed
#endif
int quote_chain_ok;
SRC
"$compiler" -E -iquote "$work/q1" -iquote "$work/q2" "$work/project/quote-chain.c" > "$work/quote-chain.i"
grep -F 'int quote_chain_ok;' "$work/quote-chain.i" >/dev/null
echo 'OK(preprocessor include_next): -iquote chain ordering'

# include_next does not use its own delimiter to restart earlier search
# classes. A header found through -I must skip -iquote even when it spells the
# next operand with quotes.
cat > "$work/i1/user-layer.h" <<'SRC'
#define USER_ONE 1
#include_next "user-layer.h"
SRC
cat > "$work/i2/user-layer.h" <<'SRC'
#define USER_TWO 2
SRC
cat > "$work/qtrap/user-layer.h" <<'SRC'
#error include_next from -I must not jump backward to -iquote
SRC
cat > "$work/project/user-chain.c" <<'SRC'
#include <user-layer.h>
#if USER_ONE != 1 || USER_TWO != 2
#error user include_next chain failed
#endif
int user_chain_ok;
SRC
"$compiler" -E -iquote "$work/qtrap" -I "$work/i1" -I "$work/i2" "$work/project/user-chain.c" > "$work/user-chain.i"
grep -F 'int user_chain_ok;' "$work/user-chain.i" >/dev/null
echo 'OK(preprocessor include_next): delimiter-independent -I continuation'

# Standard builtin headers sit after -isystem and before -idirafter. A wrapper
# stddef.h found through -I must reach the builtin rather than the poison
# after-directory copy.
cat > "$work/i1/stddef.h" <<'SRC'
#define WRAPPED_STDDEF 1
#include_next <stddef.h>
SRC
cat > "$work/after1/stddef.h" <<'SRC'
#error builtin stddef.h must win before -idirafter
SRC
cat > "$work/project/builtin-chain.c" <<'SRC'
#include <stddef.h>
#if WRAPPED_STDDEF != 1
#error wrapper stddef.h missing
#endif
size_t builtin_size;
int builtin_chain_ok;
SRC
"$compiler" -E -I "$work/i1" -idirafter "$work/after1" "$work/project/builtin-chain.c" > "$work/builtin-chain.i"
grep -F 'int builtin_chain_ok;' "$work/builtin-chain.i" >/dev/null
echo 'OK(preprocessor include_next): builtin layer precedes -idirafter'

# With builtins disabled, include_next walks user -> system -> after. The
# second hop originates inside a system header and therefore remains system.
cat > "$work/i1/multi.h" <<'SRC'
#define MULTI_USER 1
#include_next <multi.h>
SRC
cat > "$work/system/multi.h" <<'SRC'
#define MULTI_SYSTEM 2
#include_next "multi.h"
SRC
cat > "$work/after1/multi.h" <<'SRC'
#define MULTI_AFTER 3
SRC
cat > "$work/project/multi.c" <<'SRC'
#include <multi.h>
#if MULTI_USER != 1 || MULTI_SYSTEM != 2 || MULTI_AFTER != 3
#error multi-class include_next failed
#endif
int multi_ok;
SRC
"$compiler" -E -nostdinc -I "$work/i1" -isystem "$work/system" -idirafter "$work/after1" "$work/project/multi.c" > "$work/multi.i"
grep -F 'int multi_ok;' "$work/multi.i" >/dev/null
echo 'OK(preprocessor include_next): user/system/after continuation with -nostdinc'

# Multiple -idirafter directories also continue within their own class.
cat > "$work/after1/after-layer.h" <<'SRC'
#define AFTER_ONE 1
#include_next <after-layer.h>
SRC
cat > "$work/after2/after-layer.h" <<'SRC'
#define AFTER_TWO 2
SRC
cat > "$work/project/after-chain.c" <<'SRC'
#include <after-layer.h>
#if AFTER_ONE != 1 || AFTER_TWO != 2
#error after include_next chain failed
#endif
int after_chain_ok;
SRC
"$compiler" -E -idirafter "$work/after1" -idirafter "$work/after2" "$work/project/after-chain.c" > "$work/after-chain.i"
grep -F 'int after_chain_ok;' "$work/after-chain.i" >/dev/null
echo 'OK(preprocessor include_next): -idirafter chain ordering'

# A file reached through an absolute include has no search-list origin. GCC
# starts include_next from the ordinary -I chain, not from -iquote.
cat > "$work/abs/absolute-wrapper.h" <<'SRC'
#define ABS_WRAPPER 1
#include_next <absolute-next.h>
SRC
cat > "$work/qtrap/absolute-next.h" <<'SRC'
#error absolute include_next must not start at -iquote
SRC
cat > "$work/i1/absolute-next.h" <<'SRC'
#define ABS_I_NEXT 2
SRC
abs_header="$(pwd)/$work/abs/absolute-wrapper.h"
printf '#include "%s"\n#if ABS_WRAPPER != 1 || ABS_I_NEXT != 2\n#error absolute include_next failed\n#endif\nint absolute_ok;\n' "$abs_header" > "$work/project/absolute.c"
"$compiler" -E -iquote "$work/qtrap" -I "$work/i1" "$work/project/absolute.c" > "$work/absolute.i"
grep -F 'int absolute_ok;' "$work/absolute.i" >/dev/null
echo 'OK(preprocessor include_next): absolute origin restarts at -I'

# The extension is accepted in a primary source too. With no prior search
# origin it likewise starts at -I and ignores quote-only paths.
cat > "$work/qtrap/primary-next.h" <<'SRC'
#error primary include_next must not start at -iquote
SRC
cat > "$work/i1/primary-next.h" <<'SRC'
#define PRIMARY_NEXT 9
SRC
cat > "$work/project/primary-next.c" <<'SRC'
#include_next <primary-next.h>
#if PRIMARY_NEXT != 9
#error primary include_next failed
#endif
int primary_next_ok;
SRC
"$compiler" -E -iquote "$work/qtrap" -I "$work/i1" "$work/project/primary-next.c" > "$work/primary-next.i"
grep -F 'int primary_next_ok;' "$work/primary-next.i" >/dev/null
echo 'OK(preprocessor include_next): primary source fallback starts at -I'

# Macro-expanded operands follow the same rules as #include.
cat > "$work/i1/macro-next.h" <<'SRC'
#define NEXT_HEADER <macro-next.h>
#define MACRO_FIRST 1
#include_next NEXT_HEADER
SRC
cat > "$work/i2/macro-next.h" <<'SRC'
#define MACRO_SECOND 2
SRC
cat > "$work/project/macro-next.c" <<'SRC'
#include <macro-next.h>
#if MACRO_FIRST != 1 || MACRO_SECOND != 2
#error macro include_next failed
#endif
int macro_next_ok;
SRC
"$compiler" -E -I "$work/i1" -I "$work/i2" "$work/project/macro-next.c" > "$work/macro-next.i"
grep -F 'int macro_next_ok;' "$work/macro-next.i" >/dev/null
echo 'OK(preprocessor include_next): macro-expanded operand'

# #line changes logical diagnostics only; it must not erase the physical
# include origin used by include_next.
cat > "$work/i1/line-next.h" <<'SRC'
#define LINE_FIRST 1
#line 700 "virtual/line-next.h"
#include_next <line-next.h>
SRC
cat > "$work/i2/line-next.h" <<'SRC'
#define LINE_SECOND 2
SRC
cat > "$work/project/line-next.c" <<'SRC'
#include <line-next.h>
#if LINE_FIRST != 1 || LINE_SECOND != 2
#error line include_next failed
#endif
int line_next_ok;
SRC
"$compiler" -E -I "$work/i1" -I "$work/i2" "$work/project/line-next.c" > "$work/line-next.i"
grep -F 'int line_next_ok;' "$work/line-next.i" >/dev/null
echo 'OK(preprocessor include_next): #line preserves physical search origin'

# GCC suppresses the earlier -I copy of a directory that is also supplied as
# a system directory. include_next must remember the effective -isystem
# origin, otherwise it can recurse into the same file instead of advancing.
cat > "$work/dup/dup-next.h" <<'SRC'
#ifndef DUP_WRAPPER
#define DUP_WRAPPER 1
#include_next <dup-next.h>
#endif
SRC
cat > "$work/after1/dup-next.h" <<'SRC'
#define DUP_AFTER 2
SRC
cat > "$work/project/duplicate.c" <<'SRC'
#include <dup-next.h>
#if DUP_WRAPPER != 1 || DUP_AFTER != 2
#error duplicate path include_next origin failed
#endif
int duplicate_ok;
SRC
"$compiler" -E -I "$work/dup" -isystem "$work/dup" -idirafter "$work/after1" "$work/project/duplicate.c" > "$work/duplicate.i"
grep -F 'int duplicate_ok;' "$work/duplicate.i" >/dev/null
echo 'OK(preprocessor include_next): duplicate user/system path keeps system origin'

# Dependencies record every physical layer under -M, while -MM keeps the user
# wrapper and filters the system layer plus its relative private child.
cat > "$work/userdep/dep-next.h" <<'SRC'
#define DEP_USER 1
#include_next <dep-next.h>
SRC
cat > "$work/sysdep/dep-next.h" <<'SRC'
#define DEP_SYSTEM 2
#include "dep-child.h"
SRC
cat > "$work/sysdep/dep-child.h" <<'SRC'
#define DEP_CHILD 3
SRC
cat > "$work/project/deps.c" <<'SRC'
#include <dep-next.h>
#if DEP_USER != 1 || DEP_SYSTEM != 2 || DEP_CHILD != 3
#error dependency include_next failed
#endif
int deps_ok;
SRC
"$compiler" -M -I "$work/userdep" -isystem "$work/sysdep" "$work/project/deps.c" > "$work/deps-m.out"
grep -F "$work/userdep/dep-next.h" "$work/deps-m.out" >/dev/null || fail '-M missing user wrapper'
grep -F "$work/sysdep/dep-next.h" "$work/deps-m.out" >/dev/null || fail '-M missing system next header'
grep -F "$work/sysdep/dep-child.h" "$work/deps-m.out" >/dev/null || fail '-M missing system child'
"$compiler" -MM -I "$work/userdep" -isystem "$work/sysdep" "$work/project/deps.c" > "$work/deps-mm.out"
grep -F "$work/userdep/dep-next.h" "$work/deps-mm.out" >/dev/null || fail '-MM missing user wrapper'
! grep -F "$work/sysdep/dep-next.h" "$work/deps-mm.out" >/dev/null || fail '-MM kept system next header'
! grep -F "$work/sysdep/dep-child.h" "$work/deps-mm.out" >/dev/null || fail '-MM kept system child'
echo 'OK(preprocessor include_next): dependency classification'

# -MG records an unresolved next-header spelling after all later search
# locations fail.
cat > "$work/userdep/generated-wrap.h" <<'SRC'
#include_next <generated-next.h>
SRC
cat > "$work/project/generated.c" <<'SRC'
#include <generated-wrap.h>
SRC
"$compiler" -M -MG -I "$work/userdep" "$work/project/generated.c" > "$work/generated.out"
grep -F "$work/userdep/generated-wrap.h" "$work/generated.out" >/dev/null || fail '-MG missing wrapper dependency'
grep -F 'generated-next.h' "$work/generated.out" >/dev/null || fail '-MG missing unresolved include_next name'
echo 'OK(preprocessor include_next): -MG unresolved next header'

# Missing next headers from a system subtree remain system dependencies and
# disappear from -MM output.
cat > "$work/sysdep/system-generated.h" <<'SRC'
#include_next <system-generated-next.h>
SRC
cat > "$work/project/system-generated.c" <<'SRC'
#include <system-generated.h>
SRC
"$compiler" -MM -MG -isystem "$work/sysdep" "$work/project/system-generated.c" > "$work/system-generated.out"
! grep -F 'system-generated.h' "$work/system-generated.out" >/dev/null || fail '-MM kept system wrapper'
! grep -F 'system-generated-next.h' "$work/system-generated.out" >/dev/null || fail '-MM kept system missing next dependency'
echo 'OK(preprocessor include_next): -MG system filtering'

# Inactive include_next directives have no lookup or dependency side effects.
cat > "$work/i1/inactive-next.h" <<'SRC'
#if 0
#include_next <must-not-exist.h>
#endif
#define INACTIVE_SAFE 1
SRC
cat > "$work/project/inactive.c" <<'SRC'
#include <inactive-next.h>
#if INACTIVE_SAFE != 1
#error inactive include_next changed macro state
#endif
int inactive_ok;
SRC
"$compiler" -E -I "$work/i1" "$work/project/inactive.c" > "$work/inactive.i"
grep -F 'int inactive_ok;' "$work/inactive.i" >/dev/null
echo 'OK(preprocessor include_next): inactive branch is side-effect free'

# Macros introduced by a later include_next layer are visible to -dM.
"$compiler" -E -dM -I "$work/i1" -I "$work/i2" "$work/project/macro-next.c" > "$work/macro-dump.out"
grep -F '#define MACRO_SECOND 2' "$work/macro-dump.out" >/dev/null || fail '-dM missing include_next macro'
echo 'OK(preprocessor include_next): -dM observes later layer macros'
