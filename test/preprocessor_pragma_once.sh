#!/bin/bash
set -eu

fail() {
  echo "FAIL(#pragma once): $*" >&2
  exit 1
}

cleanup() {
  rm -rf tmp-pragma-once
  rm -f tmp-pragma-once-*.c tmp-pragma-once-*.i tmp-pragma-once-*.s tmp-pragma-once-*.out
}
trap cleanup EXIT

mkdir -p tmp-pragma-once/sub

# A directly repeated include must only contribute the header once.
cat > tmp-pragma-once/direct.h <<'EOF'
#pragma once
enum { DIRECT_ONCE_VALUE = 17 };
EOF
cat > tmp-pragma-once-direct.c <<'EOF'
#include "tmp-pragma-once/direct.h"
#include "tmp-pragma-once/direct.h"
int main(void) { return DIRECT_ONCE_VALUE == 17 ? 0 : 1; }
EOF
./minicc tmp-pragma-once-direct.c > tmp-pragma-once-direct.s
cc -o tmp-pragma-once-direct.out tmp-pragma-once-direct.s
./tmp-pragma-once-direct.out || fail 'direct repeated include was not deduplicated'

# Marking happens as soon as the active pragma is encountered, so a header can
# include itself after #pragma once without recursing forever.
cat > tmp-pragma-once/self.h <<'EOF'
#pragma once
#include "self.h"
enum { SELF_ONCE_VALUE = 23 };
EOF
cat > tmp-pragma-once-self.c <<'EOF'
#include "tmp-pragma-once/self.h"
int main(void) { return SELF_ONCE_VALUE == 23 ? 0 : 1; }
EOF
./minicc tmp-pragma-once-self.c > tmp-pragma-once-self.s
cc -o tmp-pragma-once-self.out tmp-pragma-once-self.s
./tmp-pragma-once-self.out || fail 'self include was not stopped by #pragma once'

# Diamond inclusion must collapse the common physical header to one expansion.
cat > tmp-pragma-once/base.h <<'EOF'
#pragma once
enum { DIAMOND_BASE_VALUE = 31 };
EOF
cat > tmp-pragma-once/left.h <<'EOF'
#include "base.h"
enum { DIAMOND_LEFT_VALUE = 1 };
EOF
cat > tmp-pragma-once/right.h <<'EOF'
#include "base.h"
enum { DIAMOND_RIGHT_VALUE = 2 };
EOF
cat > tmp-pragma-once-diamond.c <<'EOF'
#include "tmp-pragma-once/left.h"
#include "tmp-pragma-once/right.h"
int main(void) {
  return DIAMOND_BASE_VALUE == 31 && DIAMOND_LEFT_VALUE == 1 &&
         DIAMOND_RIGHT_VALUE == 2 ? 0 : 1;
}
EOF
./minicc tmp-pragma-once-diamond.c > tmp-pragma-once-diamond.s
cc -o tmp-pragma-once-diamond.out tmp-pragma-once-diamond.s
./tmp-pragma-once-diamond.out || fail 'diamond include duplicated the common header'

# Identity is physical, not textual.  #line changes the logical diagnostic file
# name but must not affect once identity; dot/dot-dot spellings, symlinks, and
# hardlinks of the same inode must all be skipped after the first inclusion.
cat > tmp-pragma-once/alias.h <<'EOF'
#line 400 "virtual-alias.h"
#pragma once
enum { ALIAS_ONCE_VALUE = 47 };
EOF
ln -s alias.h tmp-pragma-once/alias-link.h
ln tmp-pragma-once/alias.h tmp-pragma-once/alias-hard.h
cat > tmp-pragma-once-alias.c <<'EOF'
#include "tmp-pragma-once/alias.h"
#include "./tmp-pragma-once/sub/../alias.h"
#include "tmp-pragma-once/alias-link.h"
#include "tmp-pragma-once/alias-hard.h"
int main(void) { return ALIAS_ONCE_VALUE == 47 ? 0 : 1; }
EOF
./minicc tmp-pragma-once-alias.c > tmp-pragma-once-alias.s
cc -o tmp-pragma-once-alias.out tmp-pragma-once-alias.s
./tmp-pragma-once-alias.out || fail 'physical path aliases were not deduplicated'

# A pragma in an inactive conditional branch has no effect.
cat > tmp-pragma-once/inactive.h <<'EOF'
#if 0
#pragma once
#endif
#ifndef SECOND_PASS
int inactive_first_marker;
#else
int inactive_second_marker;
#endif
EOF
cat > tmp-pragma-once-inactive.c <<'EOF'
#include "tmp-pragma-once/inactive.h"
#define SECOND_PASS 1
#include "tmp-pragma-once/inactive.h"
EOF
./minicc -E tmp-pragma-once-inactive.c > tmp-pragma-once-inactive.i
grep -F 'int inactive_first_marker;' tmp-pragma-once-inactive.i >/dev/null || \
  fail 'first inactive-pragma include disappeared'
grep -F 'int inactive_second_marker;' tmp-pragma-once-inactive.i >/dev/null || \
  fail 'inactive #pragma once incorrectly suppressed the second include'

# Unknown implementation pragmas remain ignored and do not acquire once
# semantics accidentally.
cat > tmp-pragma-once/unknown.h <<'EOF'
#pragma vendor_extension once
int unknown_pragma_marker;
EOF
cat > tmp-pragma-once-unknown.c <<'EOF'
#include "tmp-pragma-once/unknown.h"
#include "tmp-pragma-once/unknown.h"
EOF
./minicc -E tmp-pragma-once-unknown.c > tmp-pragma-once-unknown.i
count=$(grep -F -c 'int unknown_pragma_marker;' tmp-pragma-once-unknown.i || true)
[ "$count" -eq 2 ] || fail "unknown pragma changed include behavior (count=$count)"

echo 'All #pragma once tests passed!'
