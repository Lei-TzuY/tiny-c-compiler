#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-stddef.c
  "$MINICC" tmp-stddef.c > tmp-stddef.s
  cc -o tmp-stddef tmp-stddef.s
  set +e
  ./tmp-stddef
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(stddef.h): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-stddef-bad.c
  if "$MINICC" tmp-stddef-bad.c > /dev/null 2>tmp-stddef.err; then
    echo 'FAIL(stddef.h): expected rejection'
    echo "$input"
    exit 1
  fi
}

# Fundamental typedefs match the LP64 target model.
assert_run 0 '#include <stddef.h>
int main(void){return sizeof(size_t)!=8||sizeof(ptrdiff_t)!=8||sizeof(wchar_t)!=4||_Alignof(max_align_t)!=8;}'

# NULL is a usable null pointer constant in assignment, comparison and condition contexts.
assert_run 0 '#include <stddef.h>
int main(void){int *p=NULL;void *q=NULL;return p!=NULL||q!=NULL||NULL?1:0;}'

# offsetof is a true integer constant expression, not a runtime address trick.
assert_run 0 '#include <stddef.h>
struct S{char a;int b;long c;};
_Static_assert(offsetof(struct S,a)==0,"a");
_Static_assert(offsetof(struct S,b)==4,"b");
_Static_assert(offsetof(struct S,c)==8,"c");
enum { C_OFF = offsetof(struct S,c) };
int bounds[offsetof(struct S,c)==8?1:-1];
int main(void){return C_OFF!=8||sizeof(bounds)!=sizeof(int);}'

# Nested record member designators accumulate offsets correctly.
assert_run 0 '#include <stddef.h>
struct I{char x;int y;};struct O{char tag;struct I inner;long tail;};
_Static_assert(offsetof(struct O,inner.y)==8,"nested");
int main(void){return offsetof(struct O,inner)!=4||offsetof(struct O,inner.y)!=8||offsetof(struct O,tail)!=16;}'

# Fixed array subscripts in a member-designator are supported as constant offsets.
assert_run 0 '#include <stddef.h>
struct A{char tag;int items[4];};
_Static_assert(offsetof(struct A,items[0])==4,"a0");
_Static_assert(offsetof(struct A,items[3])==16,"a3");
int main(void){return offsetof(struct A,items[2])!=12;}'

# Anonymous record members are traversed using the same member lookup as ordinary expressions.
assert_run 0 '#include <stddef.h>
struct A{char p;struct{char q;long value;};};
_Static_assert(offsetof(struct A,value)==16,"anonymous");
int main(void){return offsetof(struct A,value)!=16;}'

# Unions naturally produce zero member offsets, including when nested in a struct.
assert_run 0 '#include <stddef.h>
union U{int i;long l;};struct S{char c;union U u;};
int main(void){return offsetof(union U,i)!=0||offsetof(union U,l)!=0||offsetof(struct S,u.l)!=8;}'

# Repeated inclusion must preserve compatible typedefs/macros.
assert_run 0 '#include <stddef.h>
#include <stddef.h>
int main(void){size_t n=3;ptrdiff_t d=-2;return n!=3||d!=-2||NULL!=0;}'

# Invalid designators and non-record roots are diagnosed.
assert_reject '#include <stddef.h>
struct S{int x;};int main(void){return offsetof(struct S,nope);}'
assert_reject '#include <stddef.h>
int main(void){return offsetof(int,x);}'
assert_reject '#include <stddef.h>
struct S{int a[2];};int main(void){return offsetof(struct S,a[-1]);}'
assert_reject '#include <stddef.h>
struct S{int a[2];};int main(void){return offsetof(struct S,a[2]);}'

rm -f tmp-stddef.c tmp-stddef.s tmp-stddef tmp-stddef-bad.c tmp-stddef.err

echo 'All <stddef.h> tests passed!'
