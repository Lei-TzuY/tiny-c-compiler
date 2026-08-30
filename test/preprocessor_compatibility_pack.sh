#!/bin/bash
set -eu

MINICC="${MINICC:-./minicc}"
TMP=tmp-pp-compat
trap 'rm -rf "$TMP"' EXIT
rm -rf "$TMP"
mkdir -p "$TMP/user" "$TMP/next1" "$TMP/next2" "$TMP/after"

fail() {
  echo "preprocessor compatibility regression failed: $*" >&2
  exit 1
}

# #warning is active-only, non-fatal, and its payload is not macro-expanded.
cat > "$TMP/warning.c" <<'EOF'
#define WARN_TOKEN expanded_warning
#warning WARN_TOKEN
#if 0
#warning hidden_warning
#endif
int warning_survived = 1;
EOF
"$MINICC" -E "$TMP/warning.c" > "$TMP/warning.out" 2> "$TMP/warning.err"
grep -q 'warning: #warning WARN_TOKEN' "$TMP/warning.err" || fail '#warning payload/diagnostic'
! grep -q 'expanded_warning' "$TMP/warning.err" || fail '#warning unexpectedly macro-expanded'
! grep -q 'hidden_warning' "$TMP/warning.err" || fail 'inactive #warning fired'
grep -q 'warning_survived' "$TMP/warning.out" || fail '#warning stopped preprocessing'

cat > "$TMP/user/available.h" <<'EOF'
#define AVAILABLE_VALUE 41
EOF
cat > "$TMP/user/stddef.h" <<'EOF'
#define EXPLICIT_STDDEF 1
EOF
cat > "$TMP/has.c" <<'EOF'
#if !defined __has_include
#error __has_include must be defined for feature testing
#endif
#if !defined(__has_include_next)
#error __has_include_next must be defined for feature testing
#endif
#ifndef __has_include
#error __has_include must also work with ifndef/ifdef feature testing
#endif
#ifdef __has_include_next
#else
#error __has_include_next must also work with ifdef feature testing
#endif
#if !__has_include(<stddef.h>)
#error builtin stddef should be probeable
#endif
#define HEADER_NAME "available.h"
#if !__has_include(HEADER_NAME)
#error macro-expanded quoted operand failed
#endif
#if !__has_include(<available.h>)
#error explicit include path probe failed
#endif
#if __has_include("definitely-missing-minicc-header.h")
#error missing header probe returned true
#endif
int has_include_ok = 1;
EOF
"$MINICC" -E -I "$TMP/user" "$TMP/has.c" > "$TMP/has.out"
grep -q 'has_include_ok' "$TMP/has.out" || fail '__has_include basic probes'

cat > "$TMP/nostdinc.c" <<'EOF'
#if __has_include(<stddef.h>)
#error builtin must disappear under nostdinc
#endif
int nostdinc_probe_ok = 1;
EOF
"$MINICC" -E -nostdinc "$TMP/nostdinc.c" > "$TMP/nostdinc.out"
grep -q 'nostdinc_probe_ok' "$TMP/nostdinc.out" || fail '__has_include -nostdinc'

cat > "$TMP/nostdinc-explicit.c" <<'EOF'
#if !__has_include(<stddef.h>)
#error explicit -I replacement must remain visible under nostdinc
#endif
int explicit_probe_ok = 1;
EOF
"$MINICC" -E -nostdinc -I "$TMP/user" "$TMP/nostdinc-explicit.c" > "$TMP/nostdinc-explicit.out"
grep -q 'explicit_probe_ok' "$TMP/nostdinc-explicit.out" || fail '__has_include explicit path under nostdinc'

# A successful probe must not itself become a dependency.
cat > "$TMP/probe-dep.c" <<'EOF'
#if !__has_include("available.h")
#error expected available.h
#endif
int probe_only;
EOF
"$MINICC" -M -I "$TMP/user" "$TMP/probe-dep.c" > "$TMP/probe-dep.d"
! grep -q 'available\.h' "$TMP/probe-dep.d" || fail '__has_include polluted dependency list'

# include_next probing follows the physical search origin even after #line and
# accepts macro-expanded header operands. The last layer correctly sees no next.
cat > "$TMP/next1/chain.h" <<'EOF'
#line 900 "virtual-chain.h"
#define NEXT_HEADER <chain.h>
#if !__has_include_next(NEXT_HEADER)
#error first layer should see a next chain.h
#endif
#define CHAIN_ONE 11
#include_next <chain.h>
EOF
cat > "$TMP/next2/chain.h" <<'EOF'
#if __has_include_next(<chain.h>)
#error final layer must not report another chain.h
#endif
#define CHAIN_TWO 22
EOF
cat > "$TMP/next.c" <<'EOF'
#include <chain.h>
int next_probe = CHAIN_ONE + CHAIN_TWO;
EOF
"$MINICC" -E -I "$TMP/next1" -I "$TMP/next2" "$TMP/next.c" > "$TMP/next.out"
grep -q 'int next_probe = 11 + 22;' "$TMP/next.out" || fail '__has_include_next chain/origin'

# Malformed probe operands are diagnosed rather than silently becoming zero.
cat > "$TMP/bad-has.c" <<'EOF'
#if __has_include(not_a_header_name)
#endif
EOF
if "$MINICC" -E "$TMP/bad-has.c" > /dev/null 2> "$TMP/bad-has.err"; then
  fail 'malformed __has_include operand accepted'
fi
grep -q 'requires a header-name operand' "$TMP/bad-has.err" || fail 'malformed __has_include diagnostic'

# -dD emits macro definitions plus ordinary preprocessed output, including
# source #undef directives. -dN keeps only names while retaining normal output.
cat > "$TMP/dump.c" <<'EOF'
#define KEEP 123
#define FN(x) ((x) + KEEP)
#define GONE 9
#undef GONE
int dump_value = FN(1);
EOF
"$MINICC" -E -dD "$TMP/dump.c" > "$TMP/dD.out"
grep -q '^#define __STDC__ 1$' "$TMP/dD.out" || fail '-dD predefined macros'
grep -q '^#define KEEP 123$' "$TMP/dD.out" || fail '-dD object macro'
grep -q '^#define FN(x) ((x) + KEEP)$' "$TMP/dD.out" || fail '-dD function macro'
grep -q '^#undef GONE$' "$TMP/dD.out" || fail '-dD undef directive'
grep -q 'int dump_value = ((1) + 123);' "$TMP/dD.out" || fail '-dD normal output'

"$MINICC" -E -dN "$TMP/dump.c" > "$TMP/dN.out"
grep -q '^#define KEEP$' "$TMP/dN.out" || fail '-dN object macro name'
grep -q '^#define FN$' "$TMP/dN.out" || fail '-dN function macro name'
! grep -q '^#define KEEP 123$' "$TMP/dN.out" || fail '-dN leaked replacement list'
grep -q '^#undef GONE$' "$TMP/dN.out" || fail '-dN undef directive'
grep -q 'int dump_value = ((1) + 123);' "$TMP/dN.out" || fail '-dN normal output'

# Existing -dM stays final-state-only and the last dump option wins.
"$MINICC" -E -dM "$TMP/dump.c" > "$TMP/dM.out"
grep -q '^#define KEEP 123$' "$TMP/dM.out" || fail '-dM final macro'
! grep -q '^#define GONE' "$TMP/dM.out" || fail '-dM retained undefined macro'
! grep -q 'dump_value' "$TMP/dM.out" || fail '-dM emitted ordinary output'
"$MINICC" -E -dM -dD "$TMP/dump.c" > "$TMP/last-D.out"
grep -q 'dump_value' "$TMP/last-D.out" || fail 'last -dD did not win'
"$MINICC" -E -dD -dM "$TMP/dump.c" > "$TMP/last-M.out"
! grep -q 'dump_value' "$TMP/last-M.out" || fail 'last -dM did not win'
"$MINICC" -E --dump=D "$TMP/dump.c" > "$TMP/long-D.out"
grep -q 'dump_value' "$TMP/long-D.out" || fail '--dump=D'
"$MINICC" -E --dump N "$TMP/dump.c" > "$TMP/long-N.out"
grep -q '^#define KEEP$' "$TMP/long-N.out" || fail '--dump N'

# -imacros discards ordinary file text but -dD still reports definitions made
# there, and those definitions remain active in the primary source.
cat > "$TMP/macros-only.h" <<'EOF'
THIS_TEXT_MUST_NOT_ESCAPE
#define FROM_IMACROS 77
EOF
cat > "$TMP/imacros.c" <<'EOF'
int from_imacros = FROM_IMACROS;
EOF
"$MINICC" -E -dD -imacros "$TMP/macros-only.h" "$TMP/imacros.c" > "$TMP/imacros.out"
grep -q '^#define FROM_IMACROS 77$' "$TMP/imacros.out" || fail '-dD lost imacros definition'
! grep -q 'THIS_TEXT_MUST_NOT_ESCAPE' "$TMP/imacros.out" || fail '-imacros leaked ordinary text'
grep -q 'int from_imacros = 77;' "$TMP/imacros.out" || fail '-imacros definition unavailable to source'

# Long driver aliases map to the same ordered macro/include machinery.
cat > "$TMP/user/alias.h" <<'EOF'
#define ALIAS_HEADER_VALUE 3
EOF
cat > "$TMP/after/after-only.h" <<'EOF'
#define AFTER_HEADER_VALUE 5
EOF
cat > "$TMP/aliases.c" <<'EOF'
#include <alias.h>
#include <after-only.h>
#ifndef LONG_DEFINED
#error long define alias failed
#endif
#ifdef LONG_UNDEFINED
#error long undef alias failed
#endif
int aliases = LONG_DEFINED + ALIAS_HEADER_VALUE + AFTER_HEADER_VALUE;
EOF
"$MINICC" -E \
  --define-macro=LONG_DEFINED=40 \
  --define-macro LONG_UNDEFINED=1 \
  --undefine-macro=LONG_UNDEFINED \
  --include-directory="$TMP/user" \
  --include-directory-after "$TMP/after" \
  "$TMP/aliases.c" > "$TMP/aliases.out"
grep -q 'int aliases = 40 + 3 + 5;' "$TMP/aliases.out" || fail 'long driver aliases'

"$MINICC" --help > "$TMP/help.out"
grep -q -- '-dD' "$TMP/help.out" || fail 'help missing -dD'
grep -q -- '-dN' "$TMP/help.out" || fail 'help missing -dN'
grep -q -- '--define-macro' "$TMP/help.out" || fail 'help missing --define-macro'
grep -q -- '--include-directory-after' "$TMP/help.out" || fail 'help missing include-directory-after'

if "$MINICC" -dD "$TMP/dump.c" > /dev/null 2> "$TMP/no-E.err"; then
  fail '-dD without -E accepted'
fi
grep -q "macro dump options require '-E'" "$TMP/no-E.err" || fail '-dD without -E diagnostic'
if "$MINICC" -E --dump=Q "$TMP/dump.c" > /dev/null 2> "$TMP/bad-dump.err"; then
  fail 'unsupported --dump mode accepted'
fi
grep -q 'supported macro dump modes are M, D and N' "$TMP/bad-dump.err" || fail 'unsupported dump diagnostic'

echo 'All preprocessor compatibility-pack tests passed!'
