#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-static-align.c
  ./minicc tmp-static-align.c > tmp-static-align.s
  cc -o tmp-static-align tmp-static-align.s
  set +e
  ./tmp-static-align
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "static object alignment failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(static object alignment): $actual"
}

# Globals are stored in reverse declaration order internally. Put a one-byte
# object after each target declaration so it is emitted immediately before the
# target and exposes missing alignment directives deterministically.
assert_run 0 'long x=1; char pad; int main(){return (unsigned long)&x%8;}'
assert_run 0 'double x=1.25; char pad; int main(){return (unsigned long)&x%8;}'
assert_run 0 'int x=3; char pad; int main(){return (unsigned long)&x%4;}'
assert_run 0 'short x=3; char pad; int main(){return (unsigned long)&x%2;}'

# Zero-initialized storage and scalar linker-relocation storage use separate
# emitter branches and require the same type alignment guarantee.
assert_run 0 'long x; char pad; int main(){return (unsigned long)&x%8;}'
assert_run 0 'int g; int *p=&g; char pad; int main(){return (unsigned long)&p%8;}'

# Typed static aggregate images must honor their aggregate/base alignment, not
# merely preserve internal member padding.
assert_run 0 'long a[2]={1,2}; char pad; int main(){return (unsigned long)&a%8;}'
assert_run 0 'int a[2]={1,2}; char pad; int main(){return (unsigned long)&a%4;}'
assert_run 0 'struct S{char c;long x;}; struct S s={1,2}; char pad; int main(){return (unsigned long)&s%8;}'
assert_run 0 'union U{char c;long x;}; union U u={.x=7}; char pad; int main(){return (unsigned long)&u%8;}'

# Block-static objects are emitted through the same global data path despite
# being declared inside a function.
assert_run 0 'int main(){static long x=1; static char pad; return (unsigned long)&x%8;}'
assert_run 0 'int main(){struct S{char c;long x;}; static struct S s={1,2}; static char pad; return (unsigned long)&s%8;}'

echo 'All static-object alignment tests passed!'
