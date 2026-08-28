#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-fn-type.c
  ./minicc tmp-fn-type.c > tmp-fn-type.s
  cc -o tmp-fn-type tmp-fn-type.s
  set +e
  ./tmp-fn-type
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(function type): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(function type): $actual"
}

assert_accept() {
  input="$1"
  printf '%s\n' "$input" > tmp-fn-type-accept.c
  ./minicc tmp-fn-type-accept.c > tmp-fn-type-accept.s
  cc -o tmp-fn-type-accept tmp-fn-type-accept.s
  ./tmp-fn-type-accept
  echo "OK(function type): accepted declaration shape"
}

assert_reject_msg() {
  pattern="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-fn-type-reject.c
  if ./minicc tmp-fn-type-reject.c > /dev/null 2>tmp-fn-type.err; then
    echo "FAIL(function type): expected rejection"
    echo "$input"
    exit 1
  fi
  if ! grep -q "$pattern" tmp-fn-type.err; then
    echo "FAIL(function type): missing diagnostic '$pattern'"
    cat tmp-fn-type.err
    exit 1
  fi
  echo "OK(function type): rejected with $pattern"
}

# Incomplete records are representable in prototypes and become valid by-value
# ABI types once the same tagged type is completed before the definition.
assert_run 7 'struct S; int get(struct S); struct S{int x;}; int get(struct S s){return s.x;} int main(void){struct S s={7};return get(s);}'
assert_run 9 'struct S; struct S make(void); struct S{int x;}; struct S make(void){struct S s={9};return s;} int main(void){return make().x;}'
assert_run 11 'struct S; struct S id(struct S); struct S{int x;}; struct S id(struct S s){return s;} int main(void){struct S s={11};return id(s).x;}'
# A typedef naming unqualified void has the same zero-parameter meaning as (void).
assert_run 4 'typedef void V; int f(V); int f(void){return 4;} int main(void){return f();}'
# Pointer-to-void remains an ordinary parameter type.
assert_run 5 'int f(void *p){return p?5:1;} int main(void){int x=0;return f(&x);}'
# Standard variadic form requires a fixed parameter before the ellipsis.
assert_accept 'int ext(int,...); int main(void){return 0;}'
# Returning pointers to array/function types is valid; only returning those
# types themselves is forbidden.
assert_accept 'typedef int A[3]; A *factory(void); int main(void){return 0;}'
assert_accept 'typedef int F(void); F *factory(void); int main(void){return 0;}'
# A prototype may remain incomplete when no definition is present.
assert_accept 'struct Opaque; int consume(struct Opaque); struct Opaque produce(void); int main(void){return 0;}'

# Invalid void parameter forms.
assert_reject_msg 'void parameter must be the only unqualified unnamed parameter' 'int f(void x); int main(void){return 0;}'
assert_reject_msg 'void parameter must be the only unqualified unnamed parameter' 'typedef void V; int f(V x); int main(void){return 0;}'
assert_reject_msg 'void parameter must be the only unqualified unnamed parameter' 'int f(const void); int main(void){return 0;}'
assert_reject_msg 'void parameter must be the only unqualified unnamed parameter' 'int f(void,int); int main(void){return 0;}'
assert_reject_msg 'void parameter must be the only unqualified unnamed parameter' 'int f(void,...); int main(void){return 0;}'
# C11 variadic syntax needs at least one fixed parameter and disallows a
# trailing comma before ')'.
assert_reject_msg 'ellipsis requires a preceding fixed parameter' 'int f(...); int main(void){return 0;}'
assert_reject_msg 'trailing comma in parameter list' 'int f(int,); int main(void){return 0;}'

# Typedefs must not hide an illegal array/function return type.
assert_reject_msg 'function cannot return an array type' 'typedef int A[3]; A f(void); int main(void){return 0;}'
assert_reject_msg 'function cannot return a function type' 'typedef int F(void); F f(void); int main(void){return 0;}'
assert_reject_msg 'function cannot return a function type' 'typedef int F(void); typedef F G(void); int main(void){return 0;}'

# Incomplete by-value object types are allowed in a declaration, but a
# definition immediately needs their complete representation.
assert_reject_msg 'function definition has incomplete parameter type' 'struct S; int f(struct S s){return 0;} int main(void){return 0;}'
assert_reject_msg 'function definition has incomplete parameter type' 'typedef struct S S; int f(S s){return 0;} int main(void){return 0;}'
assert_reject_msg 'function definition has incomplete return type' 'struct S; struct S f(void){for(;;){}} int main(void){return 0;}'
assert_reject_msg 'function definition has incomplete return type' 'typedef struct S S; S f(void){for(;;){}} int main(void){return 0;}'

echo 'All function-type constraint tests passed!'
