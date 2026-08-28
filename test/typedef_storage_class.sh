#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-typedef-sc.c
  ./minicc tmp-typedef-sc.c > tmp-typedef-sc.s
  cc -o tmp-typedef-sc tmp-typedef-sc.s
  set +e
  ./tmp-typedef-sc
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(typedef storage): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-typedef-sc.c
  ./minicc tmp-typedef-sc.c > tmp-typedef-sc.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-typedef-sc-bad.c
  if ./minicc tmp-typedef-sc-bad.c > /dev/null 2>tmp-typedef-sc.err; then
    echo "FAIL(typedef storage): expected rejection"
    echo "$input"
    exit 1
  fi
}

# typedef is a storage-class specifier and may be intermingled with type
# specifiers/qualifiers rather than appearing only as the first token.
assert_run 7 'int typedef I;I x=7;int main(void){return x;}'
assert_run 5 'const typedef int CI;int main(void){CI x=5;return x;}'
assert_run 0 'unsigned typedef long U;int main(void){return sizeof(U)==8?0:1;}'
assert_run 0 'long typedef unsigned U;int main(void){return sizeof(U)==8?0:1;}'
assert_run 4 'struct S{int x;} typedef S;int main(void){S s={4};return s.x;}'
assert_run 6 'int main(void){int typedef I;I x=6;return x;}'
assert_run 8 'int main(void){const typedef int I;I x=8;return x;}'

# Complex declarators and comma-separated typedef declarators keep working.
assert_run 3 'typedef int I,*IP,A[3];int main(void){I x=3;IP p=&x;A a={1,2,3};return *p+a[0]-1;}'
assert_run 9 'typedef int F(int);int add1(int x){return x+1;}int main(void){F *fp=add1;return fp(8);}'
assert_run 5 'int typedef F(int);int f(int x){return x;}int main(void){F *fp=f;return fp(5);}'
assert_compile 'typedef struct Node Node;struct Node{int x;Node *next;};int main(void){return 0;}'

# A nearer ordinary identifier still shadows an outer typedef name.
assert_run 3 'typedef int T;int main(void){int T=3;return T;}'
assert_run 4 'typedef int T;int main(void){{int typedef U;U T=4;return T;}return 0;}'

# A typedef declaration requires at least one declarator and cannot initialize.
assert_reject 'typedef int;int main(void){return 0;}'
assert_reject 'int typedef;int main(void){return 0;}'
assert_reject 'const typedef int;int main(void){return 0;}'
assert_reject 'typedef int I=3;int main(void){return 0;}'
assert_reject 'int typedef I=3;int main(void){return 0;}'
assert_reject 'typedef int I,J=3;int main(void){return 0;}'

# typedef participates in the one-storage-class constraint.
assert_reject 'typedef typedef int I;int main(void){return 0;}'
assert_reject 'typedef static int I;int main(void){return 0;}'
assert_reject 'static typedef int I;int main(void){return 0;}'
assert_reject 'extern typedef int I;int main(void){return 0;}'
assert_reject 'register typedef int I;int main(void){return 0;}'
assert_reject 'auto typedef int I;int main(void){return 0;}'

# Alignment/function specifiers cannot be attached to a typedef declaration.
assert_reject '_Alignas(8) typedef long I;int main(void){return 0;}'
assert_reject 'typedef _Alignas(8) long I;int main(void){return 0;}'
assert_reject 'inline typedef int F(void);int main(void){return 0;}'
assert_reject '_Noreturn typedef void F(void);int main(void){return 0;}'

# Storage-class context rules now also apply when typedef is not first.
assert_reject 'int f(typedef int x);int main(void){return 0;}'
assert_reject 'struct S{typedef int x;};int main(void){return 0;}'
assert_reject 'int main(void){return sizeof(typedef int);}'

rm -f tmp-typedef-sc.c tmp-typedef-sc.s tmp-typedef-sc \
      tmp-typedef-sc-bad.c tmp-typedef-sc.err

echo 'All typedef storage-class tests passed!'
