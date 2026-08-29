#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-stdalign.c
  "$MINICC" tmp-stdalign.c > tmp-stdalign.s
  cc -o tmp-stdalign tmp-stdalign.s
  set +e
  ./tmp-stdalign
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(stdalign.h): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

# C11 <stdalign.h> exposes the standard convenience macros and feature macros.
assert_run 0 '#include <stdalign.h>
#if !defined(__alignas_is_defined) || !defined(__alignof_is_defined)
#error missing stdalign feature macros
#endif
int main(void){return __alignas_is_defined!=1||__alignof_is_defined!=1;}'

# alignof is a macro for _Alignof and must work with both primitive and record types.
assert_run 0 '#include <stdalign.h>
struct S { char c; long x; };
int main(void){return alignof(char)!=1||alignof(int)!=4||alignof(long)!=8||alignof(struct S)!=8;}'

# alignas is a macro for _Alignas and inherits the compiler's file/local/member semantics.
assert_run 0 '#include <stdalign.h>
alignas(16) char global_c;
struct S { char a; alignas(16) char b; };
int main(void){alignas(16) char local_c;struct S s;return (unsigned long)&global_c%16||(unsigned long)&local_c%16||(unsigned long)&s.b%16||alignof(struct S)!=16;}'

# Type-based alignas spelling is also required by the C11 header alias.
assert_run 0 '#include <stdalign.h>
alignas(long) char x;
int main(void){return (unsigned long)&x%alignof(long);}'

# Repeated inclusion must remain harmless, and normal macro controls still apply.
assert_run 0 '#include <stdalign.h>
#include <stdalign.h>
#undef alignof
#define alignof(T) 7
int main(void){return alignof(int)!=7;}'

rm -f tmp-stdalign.c tmp-stdalign.s tmp-stdalign

echo 'All <stdalign.h> tests passed!'
