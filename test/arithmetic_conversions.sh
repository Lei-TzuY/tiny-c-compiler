#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-arithconv.c
  ./minicc tmp-arithconv.c > tmp-arithconv.s
  cc -o tmp-arithconv tmp-arithconv.s
  set +e
  ./tmp-arithconv
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "arithmetic conversion failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(arithmetic conversion): $actual"
}

# Integer promotions: unsigned char/short/_Bool promote to int on LP64.
assert_run 0 'int main(){unsigned short a=1;return (a+0)<-1;}'
assert_run 0 'int main(){unsigned short a=1;return (a|0)<-1;}'
assert_run 4 'int main(){return sizeof((unsigned short)1 << (long)1);}'
assert_run 4 'int main(){return sizeof((unsigned int)1 << (long)1);}'
assert_run 4 'int main(){return sizeof((_Bool)1 << (long)1);}'

# Unary +, -, and ~ apply the integer promotions too.  Narrow unsigned types
# therefore become signed int on LP64, while unsigned int keeps its type and
# wraps at 32 bits for unary arithmetic results.
assert_run 4 'int main(){return sizeof(+(unsigned short)1);}'
assert_run 1 'int main(){return -(unsigned short)1<0;}'
assert_run 1 'int main(){return ~(unsigned short)0==-1;}'
assert_run 1 'int main(){return ~(unsigned char)0==-1;}'
assert_run 1 'int main(){return -(unsigned int)1==(unsigned int)-1;}'
assert_run 1 'int main(){return ~(unsigned int)0==(unsigned int)-1;}'

# A wider signed long represents every unsigned-int value, so long wins over
# unsigned int in the usual arithmetic conversions on this LP64 target.
assert_run 1 'int main(){unsigned int a=0;long b=-1;return (a+b)<0;}'
assert_run 0 'int main(){unsigned int a=1;long b=-1;return a<b;}'
assert_run 1 'int main(){return ((long)-1)<(unsigned int)1;}'
assert_run 1 'int main(){unsigned int a=4;long b=-2;return a/b==-2;}'
assert_run 1 'int main(){unsigned int a=5;long b=-2;return a%b==1;}'

# When the unsigned operand has the same or greater conversion rank and the
# signed type cannot represent its full range, both operands convert to the
# corresponding unsigned type.  This must affect both instruction selection
# and the value actually carried in the register.
assert_run 0 'int main(){long a=-1;unsigned long b=1;return a<b;}'
assert_run 1 'int main(){long a=-1;unsigned long b=1;return a>b;}'
assert_run 1 'int main(){unsigned long a=4;long b=-2;return a/b==0;}'
assert_run 1 'int main(){unsigned long a=5;long b=-2;return a%b==5;}'
assert_run 0 'int main(){long long a=-1;unsigned long b=1;return a<b;}'
assert_run 1 'int main(){long long a=-1;unsigned long b=1;return a>b;}'
assert_run 1 'int main(){return (1?(long)-1:(unsigned long)1)==(unsigned long)-1;}'
assert_run 1 'int main(){return (1?(long long)-1:(unsigned long)1)==(unsigned long long)-1;}'

# Conditional arithmetic alternatives use the same converted result type.
assert_run 1 'int main(){return (1?(long)-1:(unsigned int)1)<0;}'

# Compound division/remainder use the operation's converted type before the
# result is stored back into the left operand.
assert_run 1 'int main(){unsigned long x=4;long y=-2;x/=y;return x==0;}'
assert_run 1 'int main(){unsigned long x=5;long y=-2;x%=y;return x==5;}'

# Right shift uses the promoted left operand's signedness, including compound
# assignment.  Unsigned long must use a logical right shift.
assert_run 1 'int main(){unsigned long x=(unsigned long)-1;x>>=1;return (long)x>0;}'
assert_run 1 'int main(){long x=-2;x>>=1;return x==-1;}'

# Same-rank signed/unsigned conversion must change the actual register value,
# not merely the instruction signedness.  Integer results are normalized back
# to their C width so unsigned-int arithmetic wraps modulo 2^32.
assert_run 1 'int main(){int a=-2;unsigned int b=(unsigned int)-1;return a<b;}'
assert_run 1 'int main(){unsigned int a=(unsigned int)-1;return (a+1)==0;}'
assert_run 1 'int main(){unsigned int a=0;return a-1==(unsigned int)-1;}'
assert_run 1 'int main(){unsigned int a=(unsigned int)-1;return a*2==(unsigned int)-2;}'
assert_run 1 'int main(){unsigned int a=(unsigned int)-1;return (a<<1)==(unsigned int)-2;}'
assert_run 1 'int main(){int a=-2;unsigned int b=2;return a/b==(unsigned int)2147483647;}'
assert_run 1 'int main(){int a=-2;unsigned int b=7;return a%b==2;}'
assert_run 1 'int main(){int x=-2;unsigned int y=2;x/=y;return x==2147483647;}'
assert_run 1 'int main(){int a=-2;unsigned int b=0;return (a|b)==(unsigned int)-2;}'
assert_run 1 'int main(){return (1?-1:(unsigned int)0)==(unsigned int)-1;}'

echo 'All arithmetic-conversion tests passed!'
