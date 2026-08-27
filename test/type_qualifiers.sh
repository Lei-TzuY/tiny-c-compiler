#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-qual.c
  ./minicc tmp-qual.c > tmp-qual.s
  cc -o tmp-qual tmp-qual.s
  set +e
  ./tmp-qual
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "type qualifier test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(type qualifier): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-qual-bad.c
  if ./minicc tmp-qual-bad.c > tmp-qual-bad.s 2>/dev/null; then
    echo "type qualifier test unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(type qualifier): rejected invalid program"
}

# Const objects may be initialized, then read, but volatile remains modifiable.
assert_run 3 'int main(){const int x=3;return x;}'
assert_run 5 'int main(){volatile int x=1;x=5;return x;}'
assert_run 4 'int main(){const int a[2]={3,4};return a[1];}'
assert_run 5 'typedef int A[2];int main(){const A a={2,5};return a[1];}'

# Pointer target qualifiers may be added, and pointer-object qualifiers apply to
# the pointer itself rather than its pointee.
assert_run 2 'int main(){int x=2;const int *p=&x;return *p;}'
assert_run 4 'int main(){const int x=4;const int *p=&x;return *p;}'
assert_run 7 'int main(){int x=1;int *p=&x;int *const q=p;*q=7;return x;}'
assert_run 6 'int main(){int x=1;volatile int *p=&x;*p=6;return x;}'
assert_run 8 'int main(){int x=8;void *p=&x;const int *q=p;return *q;}'
assert_run 1 'int main(){int x=9;int *p=&x;const void *q=p;return q==p;}'

# Top-level parameter qualifiers are ignored for function-type compatibility,
# while the parameter object in a definition retains its qualifier.
assert_run 6 'int f(const int x){return x;}int main(){return f(6);}'
assert_run 5 'int f(const int);int f(int x){return x;}int main(){return f(5);}'
assert_run 9 'int f(int *const p){return *p;}int main(){int x=9;return f(&x);}'
assert_run 7 'int f(int *const);int f(int *p){return *p;}int main(){int x=7;return f(&x);}'

# Qualified records propagate qualifiers through . and ->, and const members
# make the containing aggregate non-modifiable while still allowing init.
assert_run 3 'struct S{int x;};int main(){struct S s={3};const struct S *p=&s;return p->x;}'
assert_run 5 'struct S{int x;};int main(){const struct S s={5};return s.x;}'
assert_run 7 'struct S{const int x;};int main(){struct S s={7};return s.x;}'
assert_run 6 'struct S{int *const p;};int main(){int x=1;struct S s={&x};*s.p=6;return x;}'

# Qualified clones of forward-declared tagged records stay linked to completion.
assert_run 8 'struct S;const struct S *gp;struct S{int x;};int main(){struct S s;s.x=8;gp=&s;return gp->x;}'

# Pointer comparison/subtraction accept differently qualified versions of the
# same pointed-to object type; conditional pointers union immediate qualifiers.
assert_run 1 'int main(){int a[2];int *p=a;const int *q=a;return p==q;}'
assert_run 1 'int main(){int a[2];int *p=a;const int *q=a+1;return q-p;}'
assert_run 4 'int main(){int x=4;int *p=&x;const int *q=&x;const int *r=1?p:q;return *r;}'

# Same-qualified file-scope redeclarations remain compatible.
assert_run 3 'extern const int x;const int x=3;int main(){return x;}'

# Const objects/pointers and aggregates containing const subobjects are not
# modifiable lvalues.
assert_fail 'int main(){const int x=1;x=2;return x;}'
assert_fail 'int main(){const int x=1;x++;return x;}'
assert_fail 'int main(){const int x=1;x+=1;return x;}'
assert_fail 'int main(){int x=1,y=2;int *const p=&x;p=&y;return x;}'
assert_fail 'struct S{int x;};int main(){const struct S s={1};s.x=2;return s.x;}'
assert_fail 'struct S{int x;};int main(){struct S s={1};const struct S *p=&s;p->x=2;return s.x;}'
assert_fail 'struct S{const int x;};int main(){struct S a={1},b={2};a=b;return a.x;}'
assert_fail 'struct S{int *const p;};int main(){int x=1,y=2;struct S s={&x};s.p=&y;return x;}'

# Pointer conversion may add immediate target qualifiers but may never discard
# them, including through void*. Nested qualification changes remain unsafe.
assert_fail 'int main(){const int x=1;int *p=&x;return *p;}'
assert_fail 'int main(){volatile int x=1;int *p=&x;return *p;}'
assert_fail 'int main(){const int *p=0;int *q=p;return 0;}'
assert_fail 'int *f(const int *p){return p;}int main(){return 0;}'
assert_fail 'int f(int *p){return *p;}int main(){const int x=1;return f(&x);}'
assert_fail 'int main(){int **p=0;const int **q=p;return 0;}'
assert_fail 'int main(){const int **p=0;int **q=p;return 0;}'
assert_fail 'int main(){const int x=1;const int *p=&x;void *q=p;return 0;}'
assert_fail 'int main(){const void *p=0;int *q=p;return 0;}'

# Qualifiers are part of object and nested parameter type compatibility, but
# top-level parameter qualification alone is ignored.
assert_fail 'extern const int x;extern int x;int main(){return 0;}'
assert_fail 'int f(const int *);int f(int *);int main(){return 0;}'

# The conditional result retains the union of pointed-to qualifiers, so it
# cannot then be assigned to a pointer that would discard const.
assert_fail 'int main(){int x=1;int *p=&x;const int *q=&x;int *r=1?p:q;return *r;}'

echo 'All type qualifier tests passed!'
