#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-stdbool.c
  "$MINICC" tmp-stdbool.c > tmp-stdbool.s
  cc -o tmp-stdbool tmp-stdbool.s
  set +e
  ./tmp-stdbool
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(stdbool.h): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

# C11 <stdbool.h> exposes the standard convenience and feature macros.
assert_run 0 '#include <stdbool.h>
#if !defined(bool) || !defined(true) || !defined(false) || !defined(__bool_true_false_are_defined)
#error missing stdbool macros
#endif
#if true != 1 || false != 0 || __bool_true_false_are_defined != 1
#error invalid stdbool macro values
#endif
int main(void){return 0;}'

# bool is an alias for _Bool, including its one-byte representation and scalar normalization.
assert_run 0 '#include <stdbool.h>
int main(void){bool a=0;bool b=42;bool c=(void *)1;return sizeof(bool)!=1||a!=false||b!=true||c!=true;}'

# Conversions through bool must canonicalize arbitrary scalar values to exactly zero or one.
assert_run 0 '#include <stdbool.h>
bool normalize(long x){return x;}
int main(void){return normalize(0)!=false||normalize(-9)!=true||normalize(123)!=true;}'

# The macros are ordinary macros: user code may undefine them without hiding the core _Bool type.
assert_run 0 '#include <stdbool.h>
#undef bool
#undef true
#undef false
int main(void){_Bool x=7;return x!=1;}'

# Repeated inclusion remains harmless and keeps the standard spellings usable.
assert_run 0 '#include <stdbool.h>
#include <stdbool.h>
int main(void){bool x=true;return !x||false;}'

rm -f tmp-stdbool.c tmp-stdbool.s tmp-stdbool

echo 'All <stdbool.h> tests passed!'
