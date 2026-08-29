#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-tag-def.c
  ./minicc tmp-tag-def.c > tmp-tag-def.s
  cc -o tmp-tag-def tmp-tag-def.s
  set +e
  ./tmp-tag-def
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(tag definition): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-tag-def-bad.c
  if ./minicc tmp-tag-def-bad.c > /dev/null 2>tmp-tag-def.err; then
    echo "FAIL(tag definition): expected C11 rejection"
    echo "$input"
    exit 1
  fi
}

# Ordinary non-empty definitions and record forward declarations remain valid.
assert_run 3 'struct S{int x;};int main(void){struct S s={3};return s.x;}'
assert_run 4 'union U{int x;long y;};int main(void){union U u={.x=4};return u.x;}'
assert_run 3 'enum E{A=1,B=3,};int main(void){return B;}'
assert_run 5 'struct S;struct S{int x;};int main(void){struct S s={5};return s.x;}'
assert_run 6 'union U;union U{int x;};int main(void){union U u={6};return u.x;}'

# Empty struct/union bodies are GNU/C23-style extensions, not C11 definitions.
assert_reject 'struct S{};int main(void){return 0;}'
assert_reject 'union U{};int main(void){return 0;}'
assert_reject 'int main(void){struct {} s;return 0;}'
assert_reject 'int main(void){union {} u;return 0;}'
assert_reject 'typedef struct {} S;int main(void){return 0;}'
assert_reject 'typedef union {} U;int main(void){return 0;}'
assert_reject 'struct O{struct I{} i;};int main(void){return 0;}'

# Enum definitions require at least one enumerator as well.
assert_reject 'enum E{};int main(void){return 0;}'
assert_reject 'int main(void){enum {} e;return 0;}'
assert_reject 'typedef enum {} E;int main(void){return 0;}'

rm -f tmp-tag-def.c tmp-tag-def.s tmp-tag-def \
      tmp-tag-def-bad.c tmp-tag-def.err

echo 'All C11 tag-definition constraint tests passed!'
