#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-voidobj.c
  ./minicc tmp-voidobj.c > tmp-voidobj.s
  cc -o tmp-voidobj tmp-voidobj.s
  set +e
  ./tmp-voidobj
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(void object): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-voidobj.c
  ./minicc tmp-voidobj.c > tmp-voidobj.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-voidobj-bad.c
  if ./minicc tmp-voidobj-bad.c > /dev/null 2>tmp-voidobj.err; then
    echo "FAIL(void object): expected rejection"
    echo "$input"
    exit 1
  fi
}

# void remains valid as a function return type and behind pointers.
assert_run 0 'void f(void){}int main(void){f();return 0;}'
assert_run 1 'int main(void){void *p=0;return p==0;}'
assert_run 3 'struct S{void *p;int x;};int main(void){struct S s={0,3};return s.x;}'
assert_compile 'typedef void V;V f(void);V *p;int main(void){return p!=0;}'

# Function types are still legal behind pointers, including as record members.
assert_run 7 'typedef int F(void);int f(void){return 7;}struct S{F *fp;};int main(void){struct S s={f};return s.fp();}'

# Direct void objects are invalid at every object-storage scope/class.
assert_reject 'void x;int main(void){return 0;}'
assert_reject 'extern void x;int main(void){return 0;}'
assert_reject 'static void x;int main(void){return 0;}'
assert_reject 'int main(void){void x;return 0;}'
assert_reject 'int main(void){auto void x;return 0;}'
assert_reject 'int main(void){register void x;return 0;}'
assert_reject 'int main(void){static void x;return 0;}'
assert_reject 'int main(void){extern void x;return 0;}'

# Typedefs must not hide an invalid void object declaration.
assert_reject 'typedef void V;V x;int main(void){return 0;}'
assert_reject 'typedef void V;int main(void){V x;return 0;}'
assert_reject 'typedef void V;int main(void){static V x;return 0;}'
assert_reject 'typedef void V;extern V x;int main(void){return 0;}'

# Record/union members are objects: direct void and direct function types are
# forbidden, while pointer forms above remain valid.
assert_reject 'struct S{void x;};int main(void){return 0;}'
assert_reject 'union U{void x;int y;};int main(void){return 0;}'
assert_reject 'typedef void V;struct S{V x;};int main(void){return 0;}'
assert_reject 'struct S{int f(void);};int main(void){return 0;}'
assert_reject 'typedef int F(void);struct S{F f;};int main(void){return 0;}'

# Arrays already enforce complete non-void object element types; keep that
# existing rule covered while tightening direct objects.
assert_reject 'void a[2];int main(void){return 0;}'
assert_reject 'typedef void V;V a[2];int main(void){return 0;}'

rm -f tmp-voidobj.c tmp-voidobj.s tmp-voidobj \
      tmp-voidobj-bad.c tmp-voidobj.err

echo 'All void-object constraint tests passed!'
