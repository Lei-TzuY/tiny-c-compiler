#!/bin/bash
set -eu

cat > tmp-source-header.h <<'EOF'
const char *header_file(void) { return __FILE__; }
int header_line(void) { return __LINE__; }
EOF

cat > tmp-source-macros.c <<'EOF'
#define LINE_VALUE() __LINE__
#define FILE_VALUE() __FILE__
#if !defined(__LINE__) || !defined(__FILE__)
#error predefined source macros must be defined
#endif
#include "tmp-source-header.h"
int streq(const char *a, const char *b) {
  while (*a && *a == *b) { a++; b++; }
  return *a == *b;
}
int main(void) {
  int a = LINE_VALUE();
  int b = LINE_VALUE();
  const char *f = FILE_VALUE();
  if (b != a + 1) return 1;
  if (!streq(f, "tmp-source-macros.c")) return 2;
  if (!streq(header_file(), "tmp-source-header.h")) return 3;
  if (header_line() != 2) return 4;
  if (!streq("__FILE__", "__FILE__")) return 5;
  return 0;
}
EOF
./minicc tmp-source-macros.c > tmp-source-macros.s
cc -o tmp-source-macros tmp-source-macros.s
./tmp-source-macros
echo "OK(predefined source macros): file/include/line context"

cat > tmp-line-if.c <<'EOF'
#if __LINE__ != 1
#error __LINE__ must work in #if
#endif
int main(void) { return __LINE__ == 4 ? 0 : 1; }
EOF
./minicc tmp-line-if.c > tmp-line-if.s
cc -o tmp-line-if tmp-line-if.s
./tmp-line-if
echo "OK(predefined source macros): __LINE__ in #if"

printf '%s\n' 'int streq(const char*a,const char*b){while(*a&&*a==*b){a++;b++;}return *a==*b;}' 'int main(void){return streq(__FILE__,"<stdin>")?0:1;}' | ./minicc - > tmp-source-stdin.s
cc -o tmp-source-stdin tmp-source-stdin.s
./tmp-source-stdin
echo "OK(predefined source macros): stdin source name"

rm -f tmp-source-header.h tmp-source-macros.c tmp-source-macros.s tmp-source-macros \
      tmp-line-if.c tmp-line-if.s tmp-line-if tmp-source-stdin.s tmp-source-stdin

echo 'All predefined __LINE__/__FILE__ tests passed!'

cat > tmp-line-remap-header.h <<'EOF'
#line 40 "virtual-header.h"
int remapped_header_line(void) { return __LINE__; }
const char *remapped_header_file(void) { return __FILE__; }
EOF

cat > tmp-line-remap.c <<'EOF'
#define TARGET_LINE 200
#define TARGET_FILE "generated-input.c"
#line TARGET_LINE TARGET_FILE
int remapped_line = __LINE__;
const char *remapped_file = __FILE__;
#include "tmp-line-remap-header.h"
int streq2(const char *a, const char *b) {
  while (*a && *a == *b) { a++; b++; }
  return *a == *b;
}
#line 700
int second_line = __LINE__;
#line 900
#if __LINE__ != 900
#error #line must affect __LINE__ in conditionals
#endif
int main(void) {
  if (remapped_line != 200) return 1;
  if (!streq2(remapped_file, "generated-input.c")) return 2;
  if (remapped_header_line() != 40) return 3;
  if (!streq2(remapped_header_file(), "virtual-header.h")) return 4;
  if (second_line != 700) return 5;
  if (!streq2(__FILE__, "generated-input.c")) return 6;
  return 0;
}
EOF
./minicc tmp-line-remap.c > tmp-line-remap.s
cc -o tmp-line-remap tmp-line-remap.s
./tmp-line-remap
echo "OK(predefined source macros): #line remaps line/file and include context"
rm -f tmp-line-remap-header.h tmp-line-remap.c tmp-line-remap.s tmp-line-remap
echo 'All #line directive tests passed!'
