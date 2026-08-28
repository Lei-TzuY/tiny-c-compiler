#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-signed.c
  ./minicc tmp-signed.c > tmp-signed.s
  cc -o tmp-signed tmp-signed.s
  set +e
  ./tmp-signed
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(signed specifier): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-signed-bad.c
  if ./minicc tmp-signed-bad.c > /dev/null 2>tmp-signed.err; then
    echo "FAIL(signed specifier): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Every standard signed integer spelling is accepted in either legal order.
assert_run 0 'int main(void){ signed a=-1; signed int b=-2; int signed c=-3; return !(a<0 && b<0 && c<0); }'
assert_run 0 'int main(void){ signed char a=-1; char signed b=-2; return !(a<0 && b<0 && sizeof(a)==1); }'
assert_run 0 'int main(void){ signed short a=-1; short signed b=-2; return !(a<0 && b<0 && sizeof(a)==2); }'
assert_run 0 'int main(void){ signed long a=-1; long signed b=-2; return !(a<0 && b<0 && sizeof(a)==8); }'
assert_run 0 'int main(void){ signed long long a=-1; long long signed b=-2; return !(a<0 && b<0 && sizeof(a)==8); }'

# Type identity for the ranked signed integer types is observable through _Generic.
assert_run 0 'int main(void){ signed x=0; signed short s=0; signed long l=0; signed long long ll=0; if(!_Generic(x,int:1,default:0))return 1; if(!_Generic(s,short:1,default:0))return 2; if(!_Generic(l,long:1,default:0))return 3; if(!_Generic(ll,long long:1,default:0))return 4; return 0; }'

# Signed spellings compose with typedef declarations, parameters, pointers and qualifiers.
assert_run 0 'typedef signed long SL; signed add(signed a, signed b){return a+b;} int main(void){ const signed int x=-3; signed int *p=(signed int *)&x; SL y=-4; return !(*p==-3 && y<0 && add(2,3)==5); }'

# Sign specifiers cannot conflict, repeat, qualify non-integer base types, or follow typedef type names.
assert_reject 'signed unsigned int x; int main(void){return 0;}'
assert_reject 'unsigned signed int x; int main(void){return 0;}'
assert_reject 'signed signed int x; int main(void){return 0;}'
assert_reject 'unsigned unsigned int x; int main(void){return 0;}'
assert_reject 'signed float x; int main(void){return 0;}'
assert_reject 'float signed x; int main(void){return 0;}'
assert_reject 'signed double x; int main(void){return 0;}'
assert_reject 'signed _Bool x; int main(void){return 0;}'
assert_reject 'signed void *p; int main(void){return 0;}'
assert_reject 'struct S{int x;}; signed struct S x; int main(void){return 0;}'
assert_reject 'enum E{A}; enum E signed x; int main(void){return 0;}'
assert_reject 'typedef int I; I signed x; int main(void){return 0;}'

rm -f tmp-signed.c tmp-signed.s tmp-signed tmp-signed-bad.c tmp-signed.err

echo 'All signed type-specifier tests passed!'
