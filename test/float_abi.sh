#!/bin/bash
set -e

assert_abi() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-float-abi.c
  "${MINICC:-./minicc}" tmp-float-abi.c > tmp-float-abi.s
  gcc -o tmp-float-abi tmp-float-abi.s
  set +e
  ./tmp-float-abi
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(float ABI): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(float ABI): $actual"
}

assert_abi 4 'double add(double a, double b) { return a+b; } int main() { return (int)add(1.5,2.5); }'
assert_abi 6 'float mul(float a, float b) { return a*b; } int main() { return (int)mul(2.0f,3.0f); }'
assert_abi 11 'double mix(int a, double b, int c, float d) { return a+b+c+d; } int main() { return (int)mix(1,2.5,3,4.5f); }'
assert_abi 3 'double ret() { return 3.75; } int main() { return (int)ret(); }'
assert_abi 5 'float retf() { return 2.5f; } int main() { return (int)(retf()*2.0f); }'
assert_abi 6 'double twice(double x) { return x*2.0; } int main() { return (int)twice(3); }'
assert_abi 3 'float idf(float x) { return x; } int main() { return (int)idf(3.75); }'
assert_abi 5 'double twice(double x); int main() { return (int)twice(2.5); } double twice(double x) { return x*2.0; }'
assert_abi 5 'double twice(double x) { return x*2.0; } int main() { double (*fp)(double)=twice; return (int)fp(2.5); }'
assert_abi 28 'double many(int a,double b,int c,double d,int e,double f,int g) { return a+b+c+d+e+f+g; } int main() { return (int)many(1,2.0,3,4.0,5,6.0,7); }'
assert_abi 36 'double sum8(double a,double b,double c,double d,double e,double f,double g,double h) { return a+b+c+d+e+f+g+h; } int main() { return (int)sum8(1,2,3,4,5,6,7,8); }'
assert_abi 2 'int main() { double x=2.0; int n=0; for (;x;x-=1.0) n++; return n; }'
assert_abi 1 'int sprintf(char *str, char *fmt, ...);
int main() { char buf[32]; int n=sprintf(buf,"%.1f",2.5); return n==3 && buf[0]=='"'"'2'"'"' && buf[1]=='"'"'.'"'"' && buf[2]=='"'"'5'"'"'; }'
assert_abi 1 'int sprintf(char *str, char *fmt, ...);
int main() { char buf[32]; float x=2.5f; int n=sprintf(buf,"%.1f",x); return n==3 && buf[0]=='"'"'2'"'"' && buf[2]=='"'"'5'"'"'; }'

# Existing integer-only generated variadic functions remain supported.
assert_abi 10 '#include <stdarg.h>
int sum(int count, ...) { va_list ap; va_start(ap,count); int s=0; for(int i=0;i<count;i++) s+=va_arg(ap,int); va_end(ap); return s; }
int main() { return sum(4,1,2,3,4); }'

echo "All floating-point ABI tests passed!"
