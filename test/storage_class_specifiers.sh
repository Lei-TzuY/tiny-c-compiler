#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-storage.c
  ./minicc tmp-storage.c > tmp-storage.s
  cc -o tmp-storage tmp-storage.s
  set +e
  ./tmp-storage
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(storage class): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-storage.c
  ./minicc tmp-storage.c > tmp-storage.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-storage-bad.c
  if ./minicc tmp-storage-bad.c > /dev/null 2>tmp-storage.err; then
    echo "FAIL(storage class): expected rejection"
    echo "$input"
    exit 1
  fi
}

# auto is a block-scope object storage class and composes with ordinary type
# specifiers/qualifiers in declaration-specifier order.
assert_run 3 'int main(void){auto int x=3;return x;}'
assert_run 4 'int main(void){int auto x=4;return x;}'
assert_run 5 'int main(void){auto const int x=5;return x;}'
assert_run 10 'int main(void){int s=0;for(auto int i=0;i<5;i++)s+=i;return s;}'
assert_run 7 'int main(void){struct S{int x;};auto struct S s={7};return s.x;}'
assert_run 9 'int main(void){auto int a=4,b=5;return a+b;}'

# register remains the one storage class permitted on parameters.
assert_run 7 'int f(register int x){return x;}int main(void){return f(7);}'
assert_compile 'int f(register int);int f(int);int main(void){return 0;}'

# Existing valid linkage/storage forms remain accepted.
assert_run 6 'int g=6;int main(void){extern int g;return g;}'
assert_run 3 'int main(void){static int x=3;return x;}'
assert_run 4 'inline int f(void){return 4;}int main(void){return f();}'
assert_compile 'int f(void);int main(void){inline int f(void);return 0;}'

# auto is not valid at file scope, on functions, parameters, or record members.
assert_reject 'auto int x;int main(void){return 0;}'
assert_reject 'int main(void){auto int f(void);return 0;}'
assert_reject 'int f(auto int x){return x;}int main(void){return 0;}'
assert_reject 'int f(static int x);int main(void){return 0;}'
assert_reject 'int f(extern int x);int main(void){return 0;}'
assert_reject 'struct S{auto int x;};int main(void){return 0;}'

# At most one storage-class specifier may occur in a declaration, including
# duplicate spellings of the same class.
assert_reject 'int main(void){auto register int x;return 0;}'
assert_reject 'int main(void){auto static int x;return 0;}'
assert_reject 'int main(void){auto extern int x;return 0;}'
assert_reject 'int main(void){static register int x;return 0;}'
assert_reject 'int main(void){extern register int x;return 0;}'
assert_reject 'int main(void){static extern int x;return 0;}'
assert_reject 'int main(void){auto auto int x;return 0;}'
assert_reject 'int main(void){register register int x;return 0;}'
assert_reject 'static static int x;int main(void){return 0;}'
assert_reject 'extern extern int x;int main(void){return 0;}'

# typedef is itself a storage class; a second storage class after typedef must
# not be silently swallowed by declspec parsing.
assert_reject 'typedef auto int T;int main(void){return 0;}'
assert_reject 'typedef static int T;int main(void){return 0;}'
assert_reject 'typedef register int T;int main(void){return 0;}'
assert_reject 'typedef extern int T;int main(void){return 0;}'
assert_reject 'int main(void){typedef auto int T;return 0;}'

# Function specifiers are valid only on function identifiers, not objects,
# parameters, record members, or typedef/type-name contexts.
assert_reject 'inline int x;int main(void){return 0;}'
assert_reject 'int main(void){inline int x;return 0;}'
assert_reject 'int f(inline int x);int main(void){return 0;}'
assert_reject 'struct S{inline int x;};int main(void){return 0;}'
assert_reject 'typedef inline int F(void);int main(void){return 0;}'

# Explicit storage classes require a declarator rather than an empty type-only
# declaration.
assert_reject 'int main(void){auto int;return 0;}'
assert_reject 'int main(void){register int;return 0;}'
assert_reject 'static int;int main(void){return 0;}'
assert_reject 'extern int;int main(void){return 0;}'

rm -f tmp-storage.c tmp-storage.s tmp-storage \
      tmp-storage-bad.c tmp-storage.err

echo 'All storage-class specifier tests passed!'
