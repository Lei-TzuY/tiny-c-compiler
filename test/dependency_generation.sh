#!/bin/bash
set -eu

fail() {
  echo "FAIL(dependency generation): $*" >&2
  exit 1
}

assert_reject() {
  pattern="$1"
  shift
  if "$@" >tmp-deps-cmd.out 2>tmp-deps-cmd.err; then
    fail "command unexpectedly succeeded: $*"
  fi
  if ! grep -F -- "$pattern" tmp-deps-cmd.err >/dev/null; then
    echo "missing diagnostic: $pattern" >&2
    cat tmp-deps-cmd.err >&2
    exit 1
  fi
}

cleanup() {
  rm -rf tmp-deps-tree 'tmp-deps-space dir'
  rm -f tmp-deps-*.c tmp-deps-*.s tmp-deps-*.d tmp-deps-*.mk \
        tmp-deps-*.out tmp-deps-cmd.out tmp-deps-cmd.err
}
trap cleanup EXIT

./minicc --help > tmp-deps-help.out
grep -F -- '-M' tmp-deps-help.out >/dev/null || fail '--help missing -M'
grep -F -- '-MD' tmp-deps-help.out >/dev/null || fail '--help missing -MD'
grep -F -- '-MF <file>' tmp-deps-help.out >/dev/null || fail '--help missing -MF'
grep -F -- '-MP' tmp-deps-help.out >/dev/null || fail '--help missing -MP'
grep -F -- '-MT <target>' tmp-deps-help.out >/dev/null || fail '--help missing -MT'
grep -F -- '-MQ <target>' tmp-deps-help.out >/dev/null || fail '--help missing -MQ'

mkdir -p tmp-deps-tree/sub 'tmp-deps-space dir'
cat > tmp-deps-tree/sub/leaf.h <<'EOF'
#pragma once
#define LEAF_VALUE 7
EOF
cat > tmp-deps-tree/root.h <<'EOF'
#pragma once
#include "sub/leaf.h"
#define ROOT_VALUE (LEAF_VALUE + 1)
EOF
ln -s root.h tmp-deps-tree/root-link.h
ln tmp-deps-tree/root.h tmp-deps-tree/root-hard.h
cat > tmp-deps-tree/extra.h <<'EOF'
#define EXTRA_VALUE 99
EOF
cat > 'tmp-deps-space dir/space header.h' <<'EOF'
#define SPACE_VALUE 3
EOF

cat > tmp-deps-main.c <<'EOF'
#define ROOT_HEADER "tmp-deps-tree/root.h"
#include ROOT_HEADER
#include "tmp-deps-tree/root-link.h"
#include "tmp-deps-tree/root-hard.h"
#include "tmp-deps-tree/sub/../root.h"
#include "tmp-deps-space dir/space header.h"
#include <stddef.h>
#if WANT_EXTRA
#include "tmp-deps-tree/extra.h"
#endif
int main(void) { return ROOT_VALUE == 8 && SPACE_VALUE == 3 ? 0 : 1; }
EOF

# -M performs real preprocessing and reports only physical file dependencies.
# Repeated path aliases of the same inode collapse to one prerequisite, builtin
# headers are not fabricated as filesystem dependencies, and Make metacharacters
# in paths/targets are escaped.
./minicc -M -MQ 'build target.s' tmp-deps-main.c > tmp-deps-basic.mk
first=$(head -n 1 tmp-deps-basic.mk)
case "$first" in
  'build\ target.s:'*) ;;
  *) fail "-MQ target was not Make-escaped: $first" ;;
esac
grep -F 'tmp-deps-main.c' tmp-deps-basic.mk >/dev/null || fail 'source prerequisite missing'
grep -F 'tmp-deps-tree/root.h' tmp-deps-basic.mk >/dev/null || fail 'root dependency missing'
grep -F 'tmp-deps-tree/sub/leaf.h' tmp-deps-basic.mk >/dev/null || fail 'nested dependency missing'
grep -F 'tmp-deps-space\ dir/space\ header.h' tmp-deps-basic.mk >/dev/null || fail 'space-containing dependency not escaped'
[ "$(grep -o 'tmp-deps-tree/root.h' tmp-deps-basic.mk | wc -l)" -eq 1 ] || fail 'physical header dependency was duplicated'
! grep -F 'root-link.h' tmp-deps-basic.mk >/dev/null || fail 'symlink alias leaked into dependency list'
! grep -F 'root-hard.h' tmp-deps-basic.mk >/dev/null || fail 'hardlink alias leaked into dependency list'
! grep -F 'extra.h' tmp-deps-basic.mk >/dev/null || fail 'inactive include became a dependency'
! grep -F 'stddef.h' tmp-deps-basic.mk >/dev/null || fail 'builtin header became a filesystem dependency'


# -MT is intentionally exact while -MQ performs Make quoting. Repeated and
# mixed target options are additive and retain argv order, matching CPP.
./minicc -M -MT '$(objpfx)raw.o' -MQ 'quoted target.o' -MT plain.o tmp-deps-main.c > tmp-deps-targets.mk
target_line=$(head -n 1 tmp-deps-targets.mk)
case "$target_line" in
  '$(objpfx)raw.o quoted\ target.o plain.o:'*) ;;
  *) fail "mixed -MT/-MQ target ordering or quoting is wrong: $target_line" ;;
esac
./minicc -M '-MQattached target.o' tmp-deps-main.c > tmp-deps-mq-attached.mk
grep -F 'attached\ target.o:' tmp-deps-mq-attached.mk >/dev/null || fail 'attached -MQ form failed'

# -MP emits one empty phony rule for every unique physical header prerequisite,
# but never for the main source or compiler-provided builtin headers.
./minicc -M -MP -MF tmp-deps-phony.mk tmp-deps-main.c
grep -Fx 'tmp-deps-tree/root.h:' tmp-deps-phony.mk >/dev/null || fail '-MP root phony rule missing'
grep -Fx 'tmp-deps-tree/sub/leaf.h:' tmp-deps-phony.mk >/dev/null || fail '-MP nested phony rule missing'
grep -Fx 'tmp-deps-space\ dir/space\ header.h:' tmp-deps-phony.mk >/dev/null || fail '-MP escaped phony rule missing'
[ "$(grep -Fx -c 'tmp-deps-tree/root.h:' tmp-deps-phony.mk || true)" -eq 1 ] || fail '-MP duplicated a physical header rule'
! grep -Fx 'tmp-deps-main.c:' tmp-deps-phony.mk >/dev/null || fail '-MP emitted a phony rule for the main source'
! grep -Fx 'stddef.h:' tmp-deps-phony.mk >/dev/null || fail '-MP emitted a phony rule for a builtin header'

# Command-line macros influence conditional dependency discovery because -M uses
# the same preprocessor as ordinary compilation.
./minicc -M -DWANT_EXTRA=1 tmp-deps-main.c > tmp-deps-extra.mk
grep -F 'tmp-deps-tree/extra.h' tmp-deps-extra.mk >/dev/null || fail '-D did not affect dependency discovery'
grep -F 'tmp-deps-main.s:' tmp-deps-extra.mk >/dev/null || fail 'default -M target is not source-basename .s'

# -MF supports separated and attached forms and keeps -M dependency output away
# from stdout when a file is requested.
./minicc -M -MF tmp-deps-separated.mk tmp-deps-main.c > tmp-deps-separated.out
test ! -s tmp-deps-separated.out || fail '-M -MF unexpectedly wrote dependencies to stdout'
test -s tmp-deps-separated.mk || fail '-M -MF did not create dependency file'
./minicc -M -MFtmp-deps-attached.mk -MTattached-target tmp-deps-main.c
grep -F 'attached-target:' tmp-deps-attached.mk >/dev/null || fail 'attached -MF/-MT forms failed'

# -MD preserves normal compilation while writing a sidecar next to an explicit
# assembly output. The dependency target defaults to the actual compiler output.
./minicc -MD -o tmp-deps-program.s tmp-deps-main.c
cc -o tmp-deps-program.out tmp-deps-program.s
./tmp-deps-program.out || fail '-MD changed compiled program behavior'
test -s tmp-deps-program.d || fail '-MD did not create output-derived .d file'
grep -F 'tmp-deps-program.s:' tmp-deps-program.d >/dev/null || fail '-MD target did not follow -o'
grep -F 'tmp-deps-tree/sub/leaf.h' tmp-deps-program.d >/dev/null || fail '-MD nested dependency missing'

# Without -o, -MD keeps assembly on stdout and derives the sidecar from the
# source basename. -MF/-MT override both defaults when requested.
./minicc -MD tmp-deps-main.c > tmp-deps-stdout.s
test -s tmp-deps-main.d || fail '-MD without -o did not create source-basename .d'
grep -F 'tmp-deps-main.s:' tmp-deps-main.d >/dev/null || fail '-MD default target is wrong'
./minicc -MD -MF tmp-deps-custom.d -MT custom-target -o tmp-deps-custom.s tmp-deps-main.c
grep -F 'custom-target:' tmp-deps-custom.d >/dev/null || fail '-MF/-MT did not override -MD defaults'
test -s tmp-deps-custom.s || fail '-MD -MF/-MT lost compiler output'

# Only the final path component contributes an extension. A dotted directory
# name must be preserved when deriving the default .d sidecar from -o.
mkdir -p tmp-deps-tree/build.v1
./minicc -MD -o tmp-deps-tree/build.v1/program.s tmp-deps-main.c
test -s tmp-deps-tree/build.v1/program.d || fail 'dotted output directory corrupted .d path derivation'
grep -F 'tmp-deps-tree/build.v1/program.s:' tmp-deps-tree/build.v1/program.d >/dev/null ||   fail 'dotted output directory corrupted dependency target'

# Invalid combinations are diagnosed rather than silently producing ambiguous
# mixed output or truncating unrelated files.
assert_reject "'-M' and '-MD' are mutually exclusive" ./minicc -M -MD tmp-deps-main.c
assert_reject "'-M' is mutually exclusive" ./minicc -M -S tmp-deps-main.c
assert_reject "'-MD' is not supported with '-E' or '-fsyntax-only'" ./minicc -MD -E tmp-deps-main.c
assert_reject "'-MF', '-MP', '-MT' and '-MQ' require '-M' or '-MD'" ./minicc -MF tmp-deps-orphan.mk tmp-deps-main.c
assert_reject "'-MF', '-MP', '-MT' and '-MQ' require '-M' or '-MD'" ./minicc -MP tmp-deps-main.c
assert_reject "'-MF', '-MP', '-MT' and '-MQ' require '-M' or '-MD'" ./minicc -MT orphan tmp-deps-main.c
assert_reject "'-MF', '-MP', '-MT' and '-MQ' require '-M' or '-MD'" ./minicc -MQ orphan tmp-deps-main.c
assert_reject "missing argument after '-MF'" ./minicc -M -MF
assert_reject "missing argument after '-MT'" ./minicc -M -MT
assert_reject "missing argument after '-MQ'" ./minicc -M -MQ
assert_reject "'-o' is not supported with '-M'; use '-MF'" ./minicc -M -o tmp-deps-bad.mk tmp-deps-main.c
assert_reject 'dependency generation requires a named input file' ./minicc -M -
assert_reject 'dependency output and compiler output cannot both use standard output' \
  ./minicc -MD -MF - tmp-deps-main.c
assert_reject 'input and dependency output files must be different' \
  ./minicc -M -MF tmp-deps-main.c tmp-deps-main.c
assert_reject 'dependency output and compiler output files must be different' \
  ./minicc -MD -MF tmp-deps-same.s -o tmp-deps-same.s tmp-deps-main.c

echo 'All dependency generation tests passed!'
