#!/bin/bash
set -eu

assert_pp() {
  expected="$1"
  input="$2"

  printf "%s\n" "$input" > tmp-pp-fn-invoke.c
  ./minicc tmp-pp-fn-invoke.c > tmp-pp-fn-invoke.s
  cc -o tmp-pp-fn-invoke tmp-pp-fn-invoke.s

  set +e
  ./tmp-pp-fn-invoke
  actual="$?"
  set -e

  if [ "$actual" != "$expected" ]; then
    echo "function-like macro invocation test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(preprocessor function invocation): $actual"
}

# A function-like macro name is replaced only when followed by a parenthesized
# argument list. In a #if expression, a non-invoked macro name therefore remains
# an identifier and is subsequently replaced with 0.
assert_pp 35 '#define PRED(x) (x)
#if PRED
int main(void) { return 1; }
#else
int main(void) { return 35; }
#endif'

# The uninvoked identifier can still participate in the surrounding expression.
assert_pp 36 '#define PRED(x) (x)
#if PRED + 1
int main(void) { return 36; }
#else
int main(void) { return 0; }
#endif'

# Whitespace between a function-like macro name and the opening parenthesis does
# not prevent invocation during preprocessing.
assert_pp 37 '#define PRED(x) (x)
#if PRED (1)
int main(void) { return 37; }
#else
int main(void) { return 0; }
#endif'

rm -f tmp-pp-fn-invoke.c tmp-pp-fn-invoke.s tmp-pp-fn-invoke

echo 'All preprocessor function-like invocation tests passed!'
