#!/bin/bash
set -eu

fail() {
  echo "FAIL(driver CLI): $*" >&2
  exit 1
}

assert_reject() {
  pattern="$1"
  shift
  if "$@" >tmp-driver-cli.out 2>tmp-driver-cli.err; then
    fail "command unexpectedly succeeded: $*"
  fi
  if ! grep -F "$pattern" tmp-driver-cli.err >/dev/null; then
    echo "missing diagnostic: $pattern" >&2
    cat tmp-driver-cli.err >&2
    exit 1
  fi
}

cat > tmp-driver-cli.c <<'EOF'
#define ANSWER 42
int main(void) { return ANSWER == 42 ? 0 : 1; }
EOF

./minicc --help > tmp-driver-help.txt
grep -F 'Usage:' tmp-driver-help.txt >/dev/null || fail '--help missing usage'
grep -F -- '-E' tmp-driver-help.txt >/dev/null || fail '--help missing -E'
grep -F -- '-fsyntax-only' tmp-driver-help.txt >/dev/null || fail '--help missing -fsyntax-only'
grep -F -- '-D<macro>' tmp-driver-help.txt >/dev/null || fail '--help missing -D'
grep -F -- '-U<macro>' tmp-driver-help.txt >/dev/null || fail '--help missing -U'
grep -F -- '-o <file>' tmp-driver-help.txt >/dev/null || fail '--help missing -o'

./minicc --version > tmp-driver-version.txt
grep -F 'tiny-c-compiler' tmp-driver-version.txt >/dev/null || fail '--version missing project name'

./minicc -E tmp-driver-cli.c > tmp-driver-cli.i
grep -F 'return 42 == 42' tmp-driver-cli.i >/dev/null || fail '-E did not expand macros'

./minicc -E -o tmp-driver-cli-output.i tmp-driver-cli.c
test -s tmp-driver-cli-output.i || fail '-E -o did not create output'
grep -F 'return 42 == 42' tmp-driver-cli-output.i >/dev/null || fail '-E -o output is wrong'

./minicc -S -o tmp-driver-cli.s tmp-driver-cli.c
grep -F '.globl main' tmp-driver-cli.s >/dev/null || fail '-S output is not assembly'
cc -o tmp-driver-cli tmp-driver-cli.s
./tmp-driver-cli

./minicc -otmp-driver-cli-attached.s tmp-driver-cli.c
cc -o tmp-driver-cli-attached tmp-driver-cli-attached.s
./tmp-driver-cli-attached


# Command-line macro definitions must participate in preprocessing before the
# source file. Attached and separated forms are both supported, and a missing
# explicit replacement defaults to 1.
cat > tmp-driver-macros.c <<'EOF'
#ifndef FEATURE
#error FEATURE missing
#endif
#ifndef FLAG
#error FLAG missing
#endif
int feature = FEATURE;
int flag = FLAG;
EOF
./minicc -E -DFEATURE=7 -DFLAG tmp-driver-macros.c > tmp-driver-macros.i
grep -F 'int feature = 7;' tmp-driver-macros.i >/dev/null || fail '-Dname=value did not expand'
grep -F 'int flag = 1;' tmp-driver-macros.i >/dev/null || fail '-Dname did not default to 1'
./minicc -E -D FEATURE=8 -D FLAG tmp-driver-macros.c > tmp-driver-macros-separated.i
grep -F 'int feature = 8;' tmp-driver-macros-separated.i >/dev/null || fail 'separated -D did not expand'

# Function-like command-line macros use the same replacement machinery as
# source #define directives.
cat > tmp-driver-function-macro.c <<'EOF'
int main(void) { return SCALE(4) == 12 ? 0 : 1; }
EOF
./minicc '-DSCALE(x)=((x)*3)' -o tmp-driver-function-macro.s tmp-driver-function-macro.c
cc -o tmp-driver-function-macro tmp-driver-function-macro.s
./tmp-driver-function-macro

# -D and -U are replayed in their original argv order after the predefined
# macros are installed and before the source is processed.
cat > tmp-driver-macro-order.c <<'EOF'
#if VALUE != 3
#error wrong VALUE ordering
#endif
int main(void) { return VALUE == 3 ? 0 : 1; }
EOF
./minicc -DVALUE=1 -UVALUE -DVALUE=3 -o tmp-driver-macro-order.s tmp-driver-macro-order.c
cc -o tmp-driver-macro-order tmp-driver-macro-order.s
./tmp-driver-macro-order

# Source definitions occur after command-line actions and therefore may
# redefine a command-line macro in the normal preprocessing stream.
cat > tmp-driver-source-redefine.c <<'EOF'
#define VALUE 9
#if VALUE != 9
#error source definition did not win
#endif
int main(void) { return 0; }
EOF
./minicc -DVALUE=3 -fsyntax-only tmp-driver-source-redefine.c

# Command-line macros are inherited by recursively processed includes, while
# command actions themselves are only replayed once at the outermost source.
cat > tmp-driver-macro-header.h <<'EOF'
#if FEATURE != 11
#error include did not inherit FEATURE
#endif
#define HEADER_VALUE FEATURE
EOF
cat > tmp-driver-macro-include.c <<'EOF'
#include "tmp-driver-macro-header.h"
int main(void) { return HEADER_VALUE == 11 ? 0 : 1; }
EOF
./minicc -DFEATURE=11 -o tmp-driver-macro-include.s tmp-driver-macro-include.c
cc -o tmp-driver-macro-include tmp-driver-macro-include.s
./tmp-driver-macro-include

# Because command actions are replayed after predefined macros are installed,
# -U can intentionally suppress a predefined macro as normal compiler drivers do.
cat > tmp-driver-undef-stdc.c <<'EOF'
#ifdef __STDC__
#error __STDC__ should have been undefined
#endif
int main(void) { return 0; }
EOF
./minicc -U__STDC__ -fsyntax-only tmp-driver-undef-stdc.c

# Syntax-only mode must run the complete front end without producing assembly or
# preprocessed output. The input deliberately uses a macro so preprocessing is
# still required before parsing and semantic validation can succeed.
./minicc -fsyntax-only tmp-driver-cli.c > tmp-driver-syntax.out
test ! -s tmp-driver-syntax.out || fail '-fsyntax-only unexpectedly produced output'

# Syntax-only mode must still diagnose front-end constraint failures rather than
# merely preprocessing and returning success.
cat > tmp-driver-semantic-bad.c <<'EOF'
int main(void) { int *p = 0; p += 1.5; return 0; }
EOF
assert_reject 'invalid operands to pointer compound assignment' \
  ./minicc -fsyntax-only tmp-driver-semantic-bad.c

printf '%s\n' 'int main(void) { return 0; }' | ./minicc -S -o tmp-driver-stdin.s -
cc -o tmp-driver-stdin tmp-driver-stdin.s
./tmp-driver-stdin

printf '%s\n' '#define V 9' 'int x = V;' | ./minicc -E -o - - > tmp-driver-stdin.i
grep -F 'int x = 9;' tmp-driver-stdin.i >/dev/null || fail 'stdin preprocess output is wrong'

printf '%s\n' '#define V 9' 'int main(void) { return V == 9 ? 0 : 1; }' | \
  ./minicc -fsyntax-only - > tmp-driver-syntax-stdin.out
test ! -s tmp-driver-syntax-stdin.out || fail 'stdin -fsyntax-only unexpectedly produced output'

cat > ./-driver-dash.c <<'EOF'
int main(void) { return 0; }
EOF
./minicc -S -o tmp-driver-dash.s -- -driver-dash.c
cc -o tmp-driver-dash tmp-driver-dash.s
./tmp-driver-dash

assert_reject 'unknown option' ./minicc -Z tmp-driver-cli.c
assert_reject "missing argument after '-D'" ./minicc -D
assert_reject "missing argument after '-U'" ./minicc -U
assert_reject 'invalid macro name in -D option' ./minicc -D9BAD=1 tmp-driver-cli.c
assert_reject 'invalid macro name in -U option' ./minicc -UBAD=1 tmp-driver-cli.c
assert_reject "missing argument after '-o'" ./minicc -o
assert_reject 'multiple input files are not supported' ./minicc tmp-driver-cli.c tmp-driver-cli.c
assert_reject "'-E', '-S' and '-fsyntax-only' are mutually exclusive" ./minicc -E -S tmp-driver-cli.c
assert_reject "'-E', '-S' and '-fsyntax-only' are mutually exclusive" \
  ./minicc -E -fsyntax-only tmp-driver-cli.c
assert_reject "'-E', '-S' and '-fsyntax-only' are mutually exclusive" \
  ./minicc -S -fsyntax-only tmp-driver-cli.c
assert_reject 'output file specified more than once' ./minicc -o a.s -o b.s tmp-driver-cli.c
assert_reject 'input and output files must be different' ./minicc -o tmp-driver-cli.c tmp-driver-cli.c
assert_reject "'-o' is not supported with '-fsyntax-only'" \
  ./minicc -fsyntax-only -o tmp-driver-syntax-output.s tmp-driver-cli.c
test ! -e tmp-driver-syntax-output.s || fail '-fsyntax-only -o created an output file'
assert_reject 'no input file' ./minicc -S

# The driver must report buffered output failures instead of exiting successfully
# after silently losing preprocessed or assembly output. /dev/full accepts open(2)
# but fails writes with ENOSPC, which exercises the final stdio flush path.
if [ -e /dev/full ]; then
  assert_reject 'failed to write output' ./minicc -E -o /dev/full tmp-driver-cli.c
  assert_reject 'failed to write output' ./minicc -S -o /dev/full tmp-driver-cli.c
fi

# Path aliases of the input must be rejected too. Otherwise freopen() would
# truncate the source through a hardlink or symlink even though the path strings
# differ.
printf '%s\n' 'int main(void) { return 0; }' > tmp-driver-alias-source.c
cp tmp-driver-alias-source.c tmp-driver-alias-expected.c
ln tmp-driver-alias-source.c tmp-driver-alias-hardlink.s
assert_reject 'input and output files must be different' \
  ./minicc -o tmp-driver-alias-hardlink.s tmp-driver-alias-source.c
cmp -s tmp-driver-alias-source.c tmp-driver-alias-expected.c || \
  fail 'hardlink output alias modified the input source'
rm -f tmp-driver-alias-hardlink.s

ln -s tmp-driver-alias-source.c tmp-driver-alias-symlink.s
assert_reject 'input and output files must be different' \
  ./minicc -E -o tmp-driver-alias-symlink.s tmp-driver-alias-source.c
cmp -s tmp-driver-alias-source.c tmp-driver-alias-expected.c || \
  fail 'symlink output alias modified the input source'

printf '%s\n' 'sentinel' > tmp-driver-preserve.s
printf '%s\n' 'int main( {' > tmp-driver-bad.c
if ./minicc -o tmp-driver-preserve.s tmp-driver-bad.c >tmp-driver-cli.out 2>tmp-driver-cli.err; then
  fail 'invalid source unexpectedly compiled'
fi
if [ "$(cat tmp-driver-preserve.s)" != 'sentinel' ]; then
  fail 'front-end failure truncated the requested output file'
fi

rm -f tmp-driver-cli.c tmp-driver-cli.i tmp-driver-cli-output.i \
      tmp-driver-cli.s tmp-driver-cli tmp-driver-cli-attached.s tmp-driver-cli-attached \
      tmp-driver-stdin.s tmp-driver-stdin tmp-driver-stdin.i \
      tmp-driver-syntax.out tmp-driver-syntax-stdin.out tmp-driver-semantic-bad.c \
      tmp-driver-syntax-output.s \
      tmp-driver-macros.c tmp-driver-macros.i tmp-driver-macros-separated.i \
      tmp-driver-function-macro.c tmp-driver-function-macro.s tmp-driver-function-macro \
      tmp-driver-macro-order.c tmp-driver-macro-order.s tmp-driver-macro-order \
      tmp-driver-source-redefine.c tmp-driver-macro-header.h tmp-driver-macro-include.c \
      tmp-driver-macro-include.s tmp-driver-macro-include tmp-driver-undef-stdc.c \
      tmp-driver-help.txt tmp-driver-version.txt tmp-driver-cli.out tmp-driver-cli.err \
      tmp-driver-preserve.s tmp-driver-bad.c ./-driver-dash.c tmp-driver-dash.s tmp-driver-dash \
      tmp-driver-alias-source.c tmp-driver-alias-expected.c tmp-driver-alias-hardlink.s \
      tmp-driver-alias-symlink.s a.s b.s

echo 'All driver CLI tests passed!'
