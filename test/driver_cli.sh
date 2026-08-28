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

printf '%s\n' 'int main(void) { return 0; }' | ./minicc -S -o tmp-driver-stdin.s -
cc -o tmp-driver-stdin tmp-driver-stdin.s
./tmp-driver-stdin

printf '%s\n' '#define V 9' 'int x = V;' | ./minicc -E -o - - > tmp-driver-stdin.i
grep -F 'int x = 9;' tmp-driver-stdin.i >/dev/null || fail 'stdin preprocess output is wrong'

cat > ./-driver-dash.c <<'EOF'
int main(void) { return 0; }
EOF
./minicc -S -o tmp-driver-dash.s -- -driver-dash.c
cc -o tmp-driver-dash tmp-driver-dash.s
./tmp-driver-dash

assert_reject 'unknown option' ./minicc -Z tmp-driver-cli.c
assert_reject "missing argument after '-o'" ./minicc -o
assert_reject 'multiple input files are not supported' ./minicc tmp-driver-cli.c tmp-driver-cli.c
assert_reject "'-E' and '-S' are mutually exclusive" ./minicc -E -S tmp-driver-cli.c
assert_reject 'output file specified more than once' ./minicc -o a.s -o b.s tmp-driver-cli.c
assert_reject 'input and output files must be different' ./minicc -o tmp-driver-cli.c tmp-driver-cli.c
assert_reject 'no input file' ./minicc -S

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
      tmp-driver-help.txt tmp-driver-version.txt tmp-driver-cli.out tmp-driver-cli.err \
      tmp-driver-preserve.s tmp-driver-bad.c ./-driver-dash.c tmp-driver-dash.s tmp-driver-dash \
      tmp-driver-alias-source.c tmp-driver-alias-expected.c tmp-driver-alias-hardlink.s \
      tmp-driver-alias-symlink.s a.s b.s

echo 'All driver CLI tests passed!'
