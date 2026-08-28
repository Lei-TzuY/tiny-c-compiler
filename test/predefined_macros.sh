#!/bin/bash
set -eu

cat > tmp-predef.c <<'EOF'
#ifndef __STDC__
#error __STDC__ missing
#endif
#ifndef __STDC_VERSION__
#error __STDC_VERSION__ missing
#endif
#ifndef __STDC_HOSTED__
#error __STDC_HOSTED__ missing
#endif
#if __STDC__ != 1
#error bad __STDC__
#endif
#if __STDC_VERSION__ != 201112L
#error bad __STDC_VERSION__
#endif
#if __STDC_HOSTED__ != 1
#error bad __STDC_HOSTED__
#endif
#define MINI_C_VERSION __STDC_VERSION__
#if MINI_C_VERSION < 201112L
#error nested expansion failed
#endif
int main(void) {
  return !(__STDC__ == 1 && __STDC_VERSION__ == 201112L && __STDC_HOSTED__ == 1);
}
EOF
./minicc tmp-predef.c > tmp-predef.s
cc -o tmp-predef tmp-predef.s
./tmp-predef

# Predefined macros are installed once for the translation unit, not on every
# recursive include. If the source deliberately undefines one, processing a
# builtin header must not silently restore it.
cat > tmp-predef.c <<'EOF'
#undef __STDC_HOSTED__
#include <stdbool.h>
#ifdef __STDC_HOSTED__
#error predefined macros were incorrectly reinitialized during include
#endif
int main(void) { return true ? 0 : 1; }
EOF
./minicc tmp-predef.c > tmp-predef.s
cc -o tmp-predef tmp-predef.s
./tmp-predef

rm -f tmp-predef.c tmp-predef.s tmp-predef

echo 'All predefined macro tests passed!'
