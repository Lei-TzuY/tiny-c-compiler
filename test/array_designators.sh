#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-array-designator.c
  ./minicc tmp-array-designator.c > tmp-array-designator.s
  cc -o tmp-array-designator tmp-array-designator.s
  set +e
  ./tmp-array-designator
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "array designator failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(array designator): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-array-designator-bad.c
  if ./minicc tmp-array-designator-bad.c > tmp-array-designator-bad.s 2>/dev/null; then
    echo "array designator unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(array designator): rejected invalid program"
}

# Static/global integer arrays support designated holes and preserve zero-fill.
assert_run 7 'int a[5]={[3]=7};int main(){return a[0]+a[1]+a[2]+a[3]+a[4];}'
assert_run 9 'int main(){static int a[5]={[4]=9};return a[0]+a[4];}'
assert_run 1 'int a[]={[4]=9};int main(){return sizeof(a)/sizeof(int)==5;}'
assert_run 1 'int a[]={[4]=7,[1]=2};int main(){return sizeof(a)/sizeof(int)==5 && a[1]==2 && a[4]==7 && a[3]==0;}'
assert_run 1 'int a[5]={[2]=4,5,6};int main(){return a[0]==0 && a[2]==4 && a[3]==5 && a[4]==6;}'
assert_run 1 'enum { K=1 };int a[5]={[K+2]=8};int main(){return a[3]==8 && a[2]==0;}'
assert_run 7 'int a[3]={[1]=2,[1]=7};int main(){return a[1];}'
assert_run 44 'unsigned char a[3]={[1]=300};int main(){return a[1];}'
assert_run 1 'long a[3]={[2]=4294967297L};int main(){return a[2]==4294967297L && a[0]==0;}'
assert_run 1 'unsigned int a[2]={[1]=4294967295U};int main(){return a[1]==4294967295U;}'
assert_run 1 'int a[3]={[2]=5,};int main(){return a[0]==0 && a[2]==5;}'

# Automatic arrays use the same full integer-constant-expression index parser.
assert_run 1 'enum { K=2 };int main(){int a[5]={[K+1]=9};return a[3]==9 && a[0]==0;}'
assert_run 1 'int main(){int a[6]={[1+2*2]=7};return a[5]==7 && a[4]==0;}'
assert_run 1 'int main(){int a[4]={[(int)2]=6};return a[2]==6 && a[1]==0;}'

# Designator indices are constrained integer constant expressions and fixed
# arrays reject indices outside their declared bound.
assert_fail 'int a[3]={[3]=1};int main(){return 0;}'
assert_fail 'int a[3]={[-1]=1};int main(){return 0;}'
assert_fail 'int a[3]={[1.5]=1};int main(){return 0;}'
assert_fail 'int x=1;int a[3]={[x]=1};int main(){return 0;}'
assert_fail 'int a[3]={.x=1};int main(){return 0;}'
assert_fail 'int a[] = {}; int main(){return 0;}'
assert_fail 'int a[]={[2147483648ULL]=1};int main(){return 0;}'

# Until typed static-record serialization exists, reject the historical packed
# integer fallback rather than silently placing members at incorrect offsets.
assert_fail 'struct S{char c;long x;};struct S s={1,2};int main(){return 0;}'

echo 'All array-designator tests passed!'
