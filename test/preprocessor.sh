#!/bin/bash

assert_pp() {
  expected="$1"
  input="$2"

  printf "%s\n" "$input" > tmp-pp.c
  "${MINICC:-./minicc}" tmp-pp.c > tmp-pp.s
  if [ $? -ne 0 ]; then
    echo "Compiler failed: $input"
    exit 1
  fi

  if command -v gcc >/dev/null; then
    gcc -o tmp-pp tmp-pp.s
  else
    as -o tmp-pp.o tmp-pp.s
    as -o tmp-pp-crt0.o test/crt0.s
    ld -o tmp-pp tmp-pp-crt0.o tmp-pp.o
  fi

  ./tmp-pp
  actual="$?"
  if [ "$actual" = "$expected" ]; then
    echo "OK(preprocessor): $actual"
  else
    echo "FAIL(preprocessor): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

# Recursive object-like macro expansion.
assert_pp 7 '#define A 4
#define B (A+3)
int main() { return B; }'

# Recursive function-like macro expansion, including nested argument expansion.
assert_pp 12 '#define ADD(a,b) ((a)+(b))
#define TWICE(x) ADD(x,x)
int main() { return TWICE(6); }'

# Zero-argument function-like macros.
assert_pp 9 '#define NINE() 9
int main() { return NINE(); }'

# #if expressions and both defined syntaxes.
assert_pp 8 '#define FEATURE 3
#if defined(FEATURE) && defined FEATURE && FEATURE*2 == 6
int main() { return 8; }
#else
int main() { return 0; }
#endif'

# #elif branch selection.
assert_pp 9 '#define MODE 2
#if MODE == 1
int main() { return 1; }
#elif MODE == 2
int main() { return 9; }
#else
int main() { return 0; }
#endif'

# #undef removes a definition.
assert_pp 11 '#define FOO 1
#undef FOO
#ifdef FOO
int main() { return 1; }
#else
int main() { return 11; }
#endif'

# Nested conditionals and a dead nested expression that must not be evaluated.
assert_pp 13 '#define OUTER 1
#if OUTER
  #if 0
    #if 1/0
    int main() { return 1; }
    #endif
  #elif 1
  int main() { return 13; }
  #endif
#else
int main() { return 0; }
#endif'

# Undefined identifiers in #if expressions evaluate to zero.
assert_pp 15 '#if UNKNOWN_IDENTIFIER
int main() { return 1; }
#else
int main() { return 15; }
#endif'

# Redefinition replaces the previous macro definition.
assert_pp 14 '#define VALUE 1
#define VALUE 14
int main() { return VALUE; }'

# Macro names inside string and character literals are not expanded.
assert_pp 1 '#define HELLO 99
#define X 1
int main() { char *s="HELLO"; return s[0]==72 && '\''X'\''==88; }'

# Macro names inside comments are not expanded; surrounding code still is.
assert_pp 7 '#define VALUE 7
int main() { /* VALUE */ return VALUE; // VALUE
}'

# Built-in header macros still work with recursive expansion enabled.
assert_pp 1 '#include <stdbool.h>
int main() { bool value = true; return value; }'

echo "All preprocessor tests passed!"
