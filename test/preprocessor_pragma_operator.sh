#!/bin/bash
set -eu

fail() {
  echo "FAIL(_Pragma): $*" >&2
  exit 1
}

cleanup() {
  rm -rf tmp-pragma-op
  rm -f tmp-pragma-op-*.c tmp-pragma-op-*.i tmp-pragma-op-*.s tmp-pragma-op-*.out tmp-pragma-op-*.err
}
trap cleanup EXIT
mkdir -p tmp-pragma-op

compile_run() {
  src=$1
  stem=$2
  ./minicc "$src" > "$stem.s"
  cc -o "$stem.out" "$stem.s"
  "./$stem.out" || fail "$stem runtime failure"
}

# Direct C99 operator form has the same physical-file once semantics as
# #pragma once, including self-inclusion after the operator has executed.
cat > tmp-pragma-op/direct.h <<'EOF'
_Pragma("once")
#include "direct.h"
enum { PRAGMA_OPERATOR_DIRECT = 17 };
EOF
cat > tmp-pragma-op-direct.c <<'EOF'
#include "tmp-pragma-op/direct.h"
#include "tmp-pragma-op/direct.h"
int main(void) { return PRAGMA_OPERATOR_DIRECT == 17 ? 0 : 1; }
EOF
compile_run tmp-pragma-op-direct.c tmp-pragma-op-direct

# The motivating C99 use case: _Pragma may be produced by macro expansion,
# including stringification of the pragma payload.
cat > tmp-pragma-op/macro.h <<'EOF'
#define DO_PRAGMA(x) _Pragma(#x)
DO_PRAGMA(once)
enum { PRAGMA_OPERATOR_MACRO = 23 };
EOF
cat > tmp-pragma-op-macro.c <<'EOF'
#include "tmp-pragma-op/macro.h"
#include "tmp-pragma-op/macro.h"
int main(void) { return PRAGMA_OPERATOR_MACRO == 23 ? 0 : 1; }
EOF
compile_run tmp-pragma-op-macro.c tmp-pragma-op-macro

# Macro replacement occurs before operator recognition, so an object-like macro
# may supply the operand and another may supply the _Pragma token itself.
cat > tmp-pragma-op/assembled.h <<'EOF'
#define PRAGMA_TOKEN _Pragma
#define ONCE_TEXT "once"
PRAGMA_TOKEN(ONCE_TEXT)
enum { PRAGMA_OPERATOR_ASSEMBLED = 29 };
EOF
cat > tmp-pragma-op-assembled.c <<'EOF'
#include "tmp-pragma-op/assembled.h"
#include "tmp-pragma-op/assembled.h"
int main(void) { return PRAGMA_OPERATOR_ASSEMBLED == 29 ? 0 : 1; }
EOF
compile_run tmp-pragma-op-assembled.c tmp-pragma-op-assembled

# C99 permits a wide string literal operand as well as an ordinary one.
cat > tmp-pragma-op/wide.h <<'EOF'
_Pragma(L"once")
enum { PRAGMA_OPERATOR_WIDE = 31 };
EOF
cat > tmp-pragma-op-wide.c <<'EOF'
#include "tmp-pragma-op/wide.h"
#include "tmp-pragma-op/wide.h"
int main(void) { return PRAGMA_OPERATOR_WIDE == 31 ? 0 : 1; }
EOF
compile_run tmp-pragma-op-wide.c tmp-pragma-op-wide

# Comments are preprocessing whitespace around the operator punctuation.
cat > tmp-pragma-op/comment-space.h <<'EOF'
_Pragma /* gap */ ( /* gap */ "once" /* gap */ )
enum { PRAGMA_OPERATOR_COMMENT_SPACE = 37 };
EOF
cat > tmp-pragma-op-comment-space.c <<'EOF'
#include "tmp-pragma-op/comment-space.h"
#include "tmp-pragma-op/comment-space.h"
int main(void) { return PRAGMA_OPERATOR_COMMENT_SPACE == 37 ? 0 : 1; }
EOF
compile_run tmp-pragma-op-comment-space.c tmp-pragma-op-comment-space

# Unknown pragmas are implementation-defined and remain ignored, while the
# operator itself contributes no preprocessing tokens to -E output.
cat > tmp-pragma-op-output.c <<'EOF'
_Pragma("vendor ignored") int pragma_output_marker = 41;
int main(void) { return pragma_output_marker == 41 ? 0 : 1; }
EOF
./minicc -E tmp-pragma-op-output.c > tmp-pragma-op-output.i
grep -F 'int pragma_output_marker = 41;' tmp-pragma-op-output.i >/dev/null || \
  fail 'ordinary tokens around _Pragma were lost'
if grep -F '_Pragma' tmp-pragma-op-output.i >/dev/null; then
  fail '_Pragma operator leaked into preprocessed output'
fi
compile_run tmp-pragma-op-output.c tmp-pragma-op-output

# Text inside string/character literals and comments is not an operator.
cat > tmp-pragma-op-literals.c <<'EOF'
char *s = "_Pragma(\"once\")";
/* _Pragma("once") */
int main(void) { return s[0] == '_' ? 0 : 1; }
EOF
./minicc -E tmp-pragma-op-literals.c > tmp-pragma-op-literals.i
grep -F '_Pragma(\"once\")' tmp-pragma-op-literals.i >/dev/null || \
  fail '_Pragma spelling inside string literal was consumed'
compile_run tmp-pragma-op-literals.c tmp-pragma-op-literals

# Block-comment state spans preprocessing lines. An operator spelling inside a
# multi-line comment must never acquire a pragma side effect.
cat > tmp-pragma-op/commented-out.h <<'EOF'
/* comment begins
_Pragma("once")
comment ends */
#ifndef COMMENT_SECOND_PASS
int pragma_comment_first;
#else
int pragma_comment_second;
#endif
EOF
cat > tmp-pragma-op-commented-out.c <<'EOF'
#include "tmp-pragma-op/commented-out.h"
#define COMMENT_SECOND_PASS 1
#include "tmp-pragma-op/commented-out.h"
EOF
./minicc -E tmp-pragma-op-commented-out.c > tmp-pragma-op-commented-out.i
grep -F 'int pragma_comment_first;' tmp-pragma-op-commented-out.i >/dev/null || \
  fail 'first multi-line-comment include disappeared'
grep -F 'int pragma_comment_second;' tmp-pragma-op-commented-out.i >/dev/null || \
  fail '_Pragma spelling inside multi-line comment executed unexpectedly'

# Inactive conditional text must not execute an operator side effect.
cat > tmp-pragma-op/inactive.h <<'EOF'
#if 0
_Pragma("once")
#endif
#ifndef SECOND_PASS
int pragma_inactive_first;
#else
int pragma_inactive_second;
#endif
EOF
cat > tmp-pragma-op-inactive.c <<'EOF'
#include "tmp-pragma-op/inactive.h"
#define SECOND_PASS 1
#include "tmp-pragma-op/inactive.h"
EOF
./minicc -E tmp-pragma-op-inactive.c > tmp-pragma-op-inactive.i
grep -F 'int pragma_inactive_first;' tmp-pragma-op-inactive.i >/dev/null || \
  fail 'first inactive-operator include disappeared'
grep -F 'int pragma_inactive_second;' tmp-pragma-op-inactive.i >/dev/null || \
  fail 'inactive _Pragma once incorrectly suppressed the second include'

# -imacros discards ordinary text but still performs preprocessing side effects.
# Marking the file once there must suppress a later forced -include of the same
# physical file while retaining macros defined by the imacros pass.
cat > tmp-pragma-op/imacros.h <<'EOF'
_Pragma("once")
#define PRAGMA_IMACROS_VALUE 43
int pragma_imacros_text_should_be_suppressed;
EOF
cat > tmp-pragma-op-imacros.c <<'EOF'
int value_from_imacros = PRAGMA_IMACROS_VALUE;
EOF
./minicc -E -imacros tmp-pragma-op/imacros.h -include tmp-pragma-op/imacros.h \
  tmp-pragma-op-imacros.c > tmp-pragma-op-imacros.i
grep -F 'int value_from_imacros = 43;' tmp-pragma-op-imacros.i >/dev/null || \
  fail 'macro from _Pragma-bearing -imacros file was lost'
if grep -F 'pragma_imacros_text_should_be_suppressed' tmp-pragma-op-imacros.i >/dev/null; then
  fail '_Pragma once side effect did not suppress later forced include'
fi

# Direct #pragma once still shares the same handler after the refactor.
cat > tmp-pragma-op/direct-pragma.h <<'EOF'
#pragma once
enum { DIRECT_PRAGMA_STILL_WORKS = 47 };
EOF
cat > tmp-pragma-op-direct-pragma.c <<'EOF'
#include "tmp-pragma-op/direct-pragma.h"
#include "tmp-pragma-op/direct-pragma.h"
int main(void) { return DIRECT_PRAGMA_STILL_WORKS == 47 ? 0 : 1; }
EOF
compile_run tmp-pragma-op-direct-pragma.c tmp-pragma-op-direct-pragma

# Malformed operators are diagnosed rather than leaking into the tokenizer.
cat > tmp-pragma-op-bad-nonstring.c <<'EOF'
_Pragma(once)
int main(void) { return 0; }
EOF
if ./minicc -E tmp-pragma-op-bad-nonstring.c > /dev/null 2> tmp-pragma-op-bad-nonstring.err; then
  fail 'non-string _Pragma operand was accepted'
fi
grep -F '_Pragma requires a parenthesized string literal' tmp-pragma-op-bad-nonstring.err >/dev/null || \
  fail 'non-string _Pragma diagnostic missing'

cat > tmp-pragma-op-bad-extra.c <<'EOF'
_Pragma("once" "extra")
int main(void) { return 0; }
EOF
if ./minicc -E tmp-pragma-op-bad-extra.c > /dev/null 2> tmp-pragma-op-bad-extra.err; then
  fail 'multiple _Pragma string operands were accepted'
fi
grep -F '_Pragma requires exactly one string literal operand' tmp-pragma-op-bad-extra.err >/dev/null || \
  fail 'extra-token _Pragma diagnostic missing'

echo 'All _Pragma operator tests passed!'
