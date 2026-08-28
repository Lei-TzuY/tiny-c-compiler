#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-restrict.c
  ./minicc tmp-restrict.c > tmp-restrict.s
  cc -o tmp-restrict tmp-restrict.s
  set +e
  ./tmp-restrict
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(restrict qualifier): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-restrict.c
  ./minicc tmp-restrict.c > tmp-restrict.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-restrict-bad.c
  if ./minicc tmp-restrict-bad.c > /dev/null 2>tmp-restrict.err; then
    echo "FAIL(restrict qualifier): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Direct pointer qualifiers and combinations with const/volatile are accepted.
assert_run 0 'int main(void){int x=3;int *restrict p=&x;*p=7;return x==7?0:1;}'
assert_run 0 'int main(void){int x=4;int *restrict const p=&x;return *p==4?0:1;}'
assert_run 0 'int main(void){int x=5;int *const restrict p=&x;return *p==5?0:1;}'
assert_run 0 'int main(void){int x=6;void *restrict p=&x;return p==&x?0:1;}'

# A typedef can expose a pointer type that is then restrict-qualified.
assert_run 0 'typedef int *IP;int main(void){int x=9;IP restrict p=&x;return *p==9?0:1;}'
assert_run 0 'typedef int *IP;typedef IP A[2];int main(void){int x=2;restrict A a={&x,&x};return *a[1]==2?0:1;}'

# Top-level parameter qualifiers are ignored for function compatibility, but
# nested restrict qualification remains part of the pointed-to type identity.
assert_run 0 'int f(int *restrict p);int f(int *p){return *p;}int main(void){int x=0;return f(&x);}'
assert_compile 'int f(int *restrict);int f(int *);int main(void){return 0;}'
assert_reject 'int f(int *restrict *);int f(int **);int main(void){return 0;}'

# Address-of preserves the restricted pointer object's nested type identity.
assert_run 0 'int main(void){int *restrict p=0;return _Generic(&p,int *restrict *:0,default:1);}'

# Same-qualified object redeclarations remain compatible; dropping the object
# qualifier in a redeclaration is a conflicting type.
assert_compile 'extern int *restrict p;extern int *restrict p;int main(void){return 0;}'
assert_reject 'extern int *restrict p;extern int *p;int main(void){return 0;}'

# restrict applies only to pointer types derived from object/incomplete types.
assert_reject 'restrict int x;int main(void){return 0;}'
assert_reject 'int restrict x;int main(void){return 0;}'
assert_reject 'restrict int *p;int main(void){return 0;}'
assert_reject 'restrict void *p;int main(void){return 0;}'
assert_reject 'int f(int restrict x);int main(void){return 0;}'
assert_reject 'struct S{int restrict x;};int main(void){return 0;}'
assert_reject 'typedef int I;restrict I x;int main(void){return 0;}'
assert_reject 'typedef int F(void);restrict F f;int main(void){return 0;}'
assert_reject 'int main(void){int (*restrict fp)(void);return 0;}'
assert_reject 'int main(void){return sizeof(restrict int);}'

rm -f tmp-restrict.c tmp-restrict.s tmp-restrict \
      tmp-restrict-bad.c tmp-restrict.err

echo 'All restrict qualifier tests passed!'
