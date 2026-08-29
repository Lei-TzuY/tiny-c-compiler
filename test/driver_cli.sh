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

# Syntax-only mode must run the complete front end without producing assembly or
# preprocessed output. The input deliberately uses a macro so preprocessing is
# still required before parsing and semantic validation can succeed.
./minicc -fsyntax-only tmp-driver-cli.c > tmp-driver-syntax.out
test ! -s tmp-driver-syntax.out || fail '-fsyntax-only unexpectedly produced output'

# Syntax-only mode must include the semantic validation pass, not merely stop
# after parsing. Pointer += floating-point is rejected by semantic_validate.c.
cat > tmp-driver-semantic-bad.c <<'EOF'
int main(void) { int *p = 0; p += 1.5; return 0; }
EOF
assert_reject 'invalid operands for additive compound assignment' \
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
      tmp-driver-help.txt tmp-driver-version.txt tmp-driver-cli.out tmp-driver-cli.err \
      tmp-driver-preserve.s tmp-driver-bad.c ./-driver-dash.c tmp-driver-dash.s tmp-driver-dash \
      tmp-driver-alias-source.c tmp-driver-alias-expected.c tmp-driver-alias-hardlink.s \
      tmp-driver-alias-symlink.s a.s b.s

echo 'All driver CLI tests passed!'
