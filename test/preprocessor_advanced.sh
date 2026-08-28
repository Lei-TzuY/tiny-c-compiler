#!/bin/bash
set -e

assert_pp_adv() {
  expected="$1"
  input="$2"

  printf "%s\n" "$input" > tmp-pp-adv.c
  "${MINICC:-./minicc}" tmp-pp-adv.c > tmp-pp-adv.s

  if command -v gcc >/dev/null; then
    gcc -o tmp-pp-adv tmp-pp-adv.s
  else
    as -o tmp-pp-adv.o tmp-pp-adv.s
    as -o tmp-pp-adv-crt0.o test/crt0.s
    ld -o tmp-pp-adv tmp-pp-adv-crt0.o tmp-pp-adv.o
  fi

  set +e
  ./tmp-pp-adv
  actual="$?"
  set -e

  if [ "$actual" = "$expected" ]; then
    echo "OK(advanced-preprocessor): $actual"
  else
    echo "FAIL(advanced-preprocessor): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_pp_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-pp-adv.c
  if "${MINICC:-./minicc}" tmp-pp-adv.c > tmp-pp-adv.s 2>/dev/null; then
    echo "FAIL(advanced-preprocessor): expected preprocessing failure"
    echo "$input"
    exit 1
  fi
  echo "OK(advanced-preprocessor): rejected invalid input"
}

# Backslash-newline splicing in object-like macros.
assert_pp_adv 9 '#define VALUE (4 + \
5)
int main() { return VALUE; }'

# Backslash-newline splicing in function-like macros.
assert_pp_adv 11 '#define SUM(a,b) ((a) + \
                  (b))
int main() { return SUM(5,6); }'

# Token pasting can form identifiers.
assert_pp_adv 7 '#define CAT(a,b) a ## b
int CAT(re,turner)() { return 7; }
int main() { return returner(); }'

# Token pasting works for variable identifiers.
assert_pp_adv 13 '#define CAT(a,b) a##b
int main() { int xy=13; return CAT(x,y); }'

# Pasted tokens are rescanned for further macro expansion.
assert_pp_adv 14 '#define X2 14
#define CAT(a,b) a##b
int main() { return CAT(X,2); }'

# Token pasting can form numeric preprocessing tokens.
assert_pp_adv 12 '#define CAT(a,b) a##b
int main() { return CAT(1,2); }'

# Stringification produces a string literal.
assert_pp_adv 104 '#define STR(x) #x
int main() { char *s=STR(hello); return s[0]; }'

# Stringification trims ends and collapses whitespace.
assert_pp_adv 32 '#define STR(x) #x
int main() { char *s=STR(  hello    world  ); return s[5]; }'

# Stringified arguments use raw tokens rather than expanded arguments.
assert_pp_adv 1 '#define NAME world
#define STR(x) #x
int main() { char *s=STR(NAME); return s[0]==78; }'

# Variadic macros expose the remaining arguments through __VA_ARGS__.
assert_pp_adv 9 '#define ADD(first, ...) ((first) + (__VA_ARGS__))
int main() { return ADD(2, 3+4); }'

# Multiple variadic arguments preserve comma separation.
assert_pp_adv 15 '#define LAST(...) (__VA_ARGS__)
int main() { return LAST(1,2,15); }'

# Variadic arguments participate in normal recursive macro expansion.
assert_pp_adv 11 '#define INC(x) ((x)+1)
#define APPLY(...) INC(__VA_ARGS__)
int main() { return APPLY(10); }'

# Empty variadic argument lists are accepted when no fixed arguments exist.
assert_pp_adv 17 '#define VALUE(...) 17
int main() { return VALUE(); }'

# Advanced macros can expand into other advanced macro invocations.
assert_pp_adv 18 '#define CAT(a,b) a##b
#define MAKE(name) CAT(name,_value)
int foo_value=18;
int main() { return MAKE(foo); }'

# Conditional directives also honor source line splicing.
assert_pp_adv 19 '#define N 1
#if N && \
    1
int main() { return 19; }
#else
int main() { return 0; }
#endif'

# #error is ignored in inactive branches.
assert_pp_adv 20 '#if 0
#error should not fire
#endif
int main() { return 20; }'

# Active #error directives stop compilation.
assert_pp_fail '#error deliberate failure
int main() { return 0; }'

# Fixed-arity macro argument mismatches are diagnosed.
assert_pp_fail '#define TWO(a,b) ((a)+(b))
int main() { return TWO(1); }'

# #if logical operators must short-circuit unevaluated operands.
assert_pp_adv 21 '#if 0 && (1 / 0)
int main() { return 0; }
#else
int main() { return 21; }
#endif'

assert_pp_adv 22 '#if 1 || (1 / 0)
int main() { return 22; }
#else
int main() { return 0; }
#endif'

# Nested skipped operands are still parsed while remaining unevaluated.
assert_pp_adv 23 '#define ZERO 0
#if ZERO && (1 || (7 % 0))
int main() { return 0; }
#elif 1 || (0 && (9 / 0))
int main() { return 23; }
#else
int main() { return 0; }
#endif'

# A zero divisor in an actually evaluated operand remains an error.
assert_pp_fail '#if 1 && (1 / 0)
int main() { return 0; }
#endif'

# #if supports the conditional operator and evaluates only the selected arm.
assert_pp_adv 24 '#if 1 ? 7 : 0
int main() { return 24; }
#else
int main() { return 0; }
#endif'

assert_pp_adv 25 '#define PICK 0
#if PICK ? (1 / 0) : 9
int main() { return 25; }
#else
int main() { return 0; }
#endif'

assert_pp_adv 26 '#if 1 ? 1 : (7 % 0)
int main() { return 26; }
#else
int main() { return 0; }
#endif'

# Conditional expressions associate to the right and nest in either arm.
assert_pp_adv 27 '#if 0 ? 0 : 1 ? 3 : 0
int main() { return 27; }
#else
int main() { return 0; }
#endif'

# The selected arm is still evaluated normally.
assert_pp_fail '#if 1 ? (1 / 0) : 1
int main() { return 0; }
#endif'

# Malformed conditional expressions are diagnosed.
assert_pp_fail '#if 1 ? 2
int main() { return 0; }
#endif'

# Function-like macros are expanded in #if expressions, including nested calls.
assert_pp_adv 28 '#define ID(x) (x)
#if ID(1)
int main() { return 28; }
#else
int main() { return 0; }
#endif'

assert_pp_adv 29 '#define ADD(a,b) ((a) + (b))
#define TWICE(x) ADD((x), (x))
#if TWICE(3) == 6
int main() { return 29; }
#else
int main() { return 0; }
#endif'

# Arguments are macro-expanded before ordinary substitution.
assert_pp_adv 30 '#define ONE 1
#define ID(x) (x)
#if ID(ONE)
int main() { return 30; }
#else
int main() { return 0; }
#endif'

# Short-circuited macro expansions are parsed without evaluating zero divisors.
assert_pp_adv 31 '#define BAD() (1 / 0)
#if 0 && BAD()
int main() { return 0; }
#else
int main() { return 31; }
#endif'

assert_pp_adv 32 '#define BAD (1 / 0)
#if 1 || BAD
int main() { return 32; }
#else
int main() { return 0; }
#endif'

# A selected function-like macro arm still diagnoses division by zero.
assert_pp_fail '#define BAD() (1 / 0)
#if BAD()
int main() { return 0; }
#endif'

# Function-like macro argument count is validated in #if expressions.
assert_pp_fail '#define PICK(x) (x)
#if PICK(1, 2)
int main() { return 0; }
#endif'

echo "All advanced preprocessor tests passed!"
