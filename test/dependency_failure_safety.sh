#!/bin/bash
set -eu

fail() {
  echo "FAIL(dependency failure safety): $*" >&2
  exit 1
}

cleanup() {
  rm -f tmp-depfail-*.c tmp-depfail-*.h tmp-depfail-*.d tmp-depfail-*.s \
        tmp-depfail-*.mk tmp-depfail-*.out tmp-depfail-*.err tmp-depfail-sentinel
}
trap cleanup EXIT

cat > tmp-depfail-header.h <<'EOF'
#define DEPFAIL_VALUE 42
EOF

cat > tmp-depfail-syntax.c <<'EOF'
#include "tmp-depfail-header.h"
int main(void) { return DEPFAIL_VALUE
EOF

# -M only preprocesses, so malformed C syntax must not prevent dependency output.
./minicc -M tmp-depfail-syntax.c > tmp-depfail-only.mk
grep -F 'tmp-depfail-syntax.c' tmp-depfail-only.mk >/dev/null || fail '-M lost source dependency on malformed C'
grep -F 'tmp-depfail-header.h' tmp-depfail-only.mk >/dev/null || fail '-M lost header dependency on malformed C'

# -MD is a compilation side effect. A front-end failure must not replace a
# pre-existing dependency file or create/truncate the assembly output.
printf '%s\n' 'keep-existing-dependency-file' > tmp-depfail-existing.d
cp tmp-depfail-existing.d tmp-depfail-sentinel
if ./minicc -MD -MF tmp-depfail-existing.d -o tmp-depfail-syntax.s \
     tmp-depfail-syntax.c >tmp-depfail-syntax.out 2>tmp-depfail-syntax.err; then
  fail '-MD unexpectedly accepted malformed syntax'
fi
cmp -s tmp-depfail-existing.d tmp-depfail-sentinel || fail '-MD rewrote existing .d before syntax validation succeeded'
test ! -e tmp-depfail-syntax.s || fail '-MD created compiler output after syntax failure'

cat > tmp-depfail-semantic.c <<'EOF'
#include "tmp-depfail-header.h"
int main(void) {
  break;
  return DEPFAIL_VALUE;
}
EOF

# The same guarantee applies to semantic validation and to the implicit .d path.
rm -f tmp-depfail-semantic.d tmp-depfail-semantic.s
if ./minicc -MD -o tmp-depfail-semantic.s tmp-depfail-semantic.c \
     >tmp-depfail-semantic.out 2>tmp-depfail-semantic.err; then
  fail '-MD unexpectedly accepted semantic error'
fi
test ! -e tmp-depfail-semantic.d || fail '-MD left a new .d after semantic failure'
test ! -e tmp-depfail-semantic.s || fail '-MD left compiler output after semantic failure'

echo 'All dependency failure-safety tests passed!'
