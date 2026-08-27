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

# A wider signed long represents every unsigned-int value, so long wins over
# unsigned int in the usual arithmetic conversions on this LP64 target.
assert_run 1 'int main(){unsigned int a=0;long b=-1;return (a+b)<0;}'
assert_run 0 'int main(){unsigned int a=1;long b=-1;return a<b;}'
assert_run 1 'int main(){return ((long)-1)<(unsigned int)1;}'
assert_run 1 'int main(){unsigned int a=4;long b=-2;return a/b==-2;}'
assert_run 1 'int main(){unsigned int a=5;long b=-2;return a%b==1;}'

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

echo 'All arithmetic-conversion tests passed!'
