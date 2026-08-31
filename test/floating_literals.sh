#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-floating-literal.c
  ./minicc tmp-floating-literal.c > tmp-floating-literal.s
  cc -o tmp-floating-literal tmp-floating-literal.s
  set +e
  ./tmp-floating-literal
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "floating literal test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(floating literal): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-floating-literal.c
  if ./minicc tmp-floating-literal.c > tmp-floating-literal.s 2>/dev/null; then
    echo "floating literal test unexpectedly accepted invalid input"
    echo "$input"
    exit 1
  fi
  echo "OK(floating literal): rejected invalid input"
}

# Decimal floating constants: fraction, exponent and f/F suffix forms.
assert_run 4  'int main(){return sizeof(1.0f);}'
assert_run 8  'int main(){return sizeof(1e0);}'
assert_run 100 'int main(){return (int)1e2;}'
assert_run 100 'int main(){return (int)1E+2F;}'
assert_run 5  'int main(){return (int)(.5*10);}'
assert_run 7  'int main(){return (int)(1.*7);}'
assert_run 1  'int main(){return (int)(1e-1*10);}'
assert_run 3  'int main(){return _Generic(1e0,double:3,float:4);}'
assert_run 4  'int main(){return _Generic(1e0F,double:3,float:4);}'

# C99 hexadecimal floating constants require a p/P binary exponent.
assert_run 16 'int main(){return (int)0x1p4;}'
assert_run 6  'int main(){return (int)0x1.8p2;}'
assert_run 4  'int main(){return (int)0X.8P+3;}'
assert_run 8  'int main(){return (int)0x1.p3F;}'

# Static initialization uses the same literal token types and values.
assert_run 10 'double x=0x1.4p3; int main(){return (int)x;}'
assert_run 10 'float x=2.5e0F; int main(){return (int)(x*4);}'

# Nearby integer spellings must remain integers, not float-suffix extensions.
assert_run 31 'int main(){return 0x1f;}'
assert_run 8  'int main(){return sizeof(1L);}'
assert_run 32 'int main(){return 0x1e+2;}'

# A suffix alone cannot turn an integer constant into a floating constant.
assert_reject 'int main(){return (int)1f;}'

# Decimal exponent syntax requires at least one exponent digit.
assert_reject 'int main(){return (int)1e;}'
assert_reject 'int main(){return (int)1e+;}'
assert_reject 'int main(){return (int)1e-;}'
assert_reject 'int main(){return (int).5e;}'
assert_reject 'int main(){return (int).5e+;}'

# Hexadecimal floating syntax always requires p/P and valid exponent digits.
assert_reject 'int main(){return (int)0x1.8;}'
assert_reject 'int main(){return (int)0x.8;}'
assert_reject 'int main(){return (int)0x.p1;}'
assert_reject 'int main(){return (int)0x1p;}'
assert_reject 'int main(){return (int)0x1p+;}'
assert_reject 'int main(){return (int)0x1p-;}'

# Unsupported floating suffix spellings remain rejected.
assert_reject 'int main(){return (int)1.0u;}'
assert_reject 'int main(){return (int)1.0ff;}'
assert_reject 'int main(){return (int)1e2foo;}'
assert_reject 'int main(){return (int)0x1p2u;}'

# C long-double suffixes select the x87 extended type for both decimal and
# hexadecimal constants. Lower-case and upper-case suffixes are equivalent.
assert_run 16 'int main(){return sizeof(1.0L);}'
assert_run 5  'int main(){return _Generic(.5l,long double:5,double:3,float:4);}'
assert_run 4  'int main(){return (int)0x1p2L;}'

echo 'All floating literal grammar tests passed!'
