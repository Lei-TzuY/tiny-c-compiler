#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-noreturn.c
  ./minicc tmp-noreturn.c > tmp-noreturn.s
  cc -o tmp-noreturn tmp-noreturn.s
  set +e
  ./tmp-noreturn
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(_Noreturn): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-noreturn.c
  ./minicc tmp-noreturn.c > tmp-noreturn.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-noreturn-bad.c
  if ./minicc tmp-noreturn-bad.c > /dev/null 2>tmp-noreturn.err; then
    echo "FAIL(_Noreturn): expected rejection"
    echo "$input"
    exit 1
  fi
}

assert_run 0 '_Noreturn void stop(void){for(;;){}} int main(void){return 0;}'
assert_run 0 'static inline _Noreturn int stop(void){for(;;){}} int main(void){return 0;}'
assert_run 0 '_Noreturn void f(void); void f(void){for(;;){}} int main(void){return 0;}'
assert_run 0 'void g(void); _Noreturn void g(void){for(;;){}} int main(void){return 0;}'
assert_run 0 '_Noreturn void f(void){for(;;){}} int main(void){ _Noreturn void f(void); return 0; }'

assert_run 0 $'#include <stdnoreturn.h>\nnoreturn void fatal(void){for(;;){}}\nint main(void){return 0;}'
assert_compile $'#include <stdnoreturn.h>\n#ifndef noreturn\n#error noreturn macro missing\n#endif\nnoreturn void fatal(void);\nint main(void){return 0;}'

# _Noreturn is a function specifier, not part of the function type.
assert_compile '_Noreturn int f(int); int f(int x){return x;} int main(void){return 0;}'

assert_reject '_Noreturn int x; int main(void){return 0;}'
assert_reject 'int main(void){ _Noreturn int x; return 0; }'
assert_reject '_Noreturn void (*fp)(void); int main(void){return 0;}'
assert_reject '_Noreturn struct S { int x; }; int main(void){return 0;}'
assert_reject 'typedef _Noreturn void F(void); int main(void){return 0;}'
assert_reject 'int main(void){ return sizeof(_Noreturn int); }'
assert_reject 'struct S { _Noreturn int x; }; int main(void){return 0;}'

rm -f tmp-noreturn.c tmp-noreturn.s tmp-noreturn \
      tmp-noreturn-bad.c tmp-noreturn.err

echo 'All C11 _Noreturn tests passed!'
