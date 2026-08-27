#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-ptrarith.c
  ./minicc tmp-ptrarith.c > tmp-ptrarith.s
  cc -o tmp-ptrarith tmp-ptrarith.s
  set +e
  ./tmp-ptrarith
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "pointer arithmetic failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(pointer arithmetic): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-ptrarith-bad.c
  if ./minicc tmp-ptrarith-bad.c > tmp-ptrarith-bad.s 2>/dev/null; then
    echo "pointer arithmetic unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(pointer arithmetic): rejected invalid program"
}

# Object-pointer arithmetic scales by the pointed-to object size.
assert_run 7 'int main(){int a[4];a[2]=7;int *p=a;return *(p+2);}'
assert_run 9 'int main(){int a[4];a[2]=9;int *p=a;return *(2+p);}'
assert_run 5 'int main(){int a[4];a[1]=5;int *p=a+2;p-=1;return *p;}'
assert_run 8 'int main(){int a[5];a[3]=8;int *p=a;p+=3;return *p;}'
assert_run 3 'int main(){int a[6];return (&a[4]-&a[1]);}'
assert_run 4 'int main(){char a[8];return (&a[6]-&a[2]);}'
assert_run 2 'struct S{int x;int y;};int main(){struct S a[4];struct S *p=&a[3];struct S *q=&a[1];return p-q;}'
assert_run 6 'int main(){int a[3];a[1]=6;int *p=a;p++;return *p;}'
assert_run 4 'int main(){int a[3];a[1]=4;int *p=a+2;--p;return *p;}'
assert_run 1 'int main(){int a[2][3];int (*p)[3]=a;p++;return p-a;}'

# void*, function pointers, incomplete objects and non-integral offsets are not
# valid pointer-arithmetic operands in standard C.
assert_fail 'int main(){void *p; p=p+1; return 0;}'
assert_fail 'int main(){void *p; p=1+p; return 0;}'
assert_fail 'int main(){void *p; p=p-1; return 0;}'
assert_fail 'int main(){void *p; p+=1; return 0;}'
assert_fail 'int main(){void *p; p++; return 0;}'
assert_fail 'int f(){return 0;} int main(){int (*p)()=f; p=p+1; return 0;}'
assert_fail 'int f(){return 0;} int main(){int (*p)()=f; p=p-1; return 0;}'
assert_fail 'int f(){return 0;} int main(){int (*p)()=f; ++p; return 0;}'
assert_fail 'struct S; int main(){struct S *p; p=p+1; return 0;}'
assert_fail 'int main(){int a[2];int *p=a;p=p+1.5;return 0;}'
assert_fail 'int main(){int a[2];int *p=a;int *q=a;p=p+q;return 0;}'
assert_fail 'int main(){int a[2];int *p=a;return 1-p;}'
assert_fail 'int main(){int a[2];double b[2];return a-b;}'
assert_fail 'int f(){return 0;} int main(){int (*p)()=f;int (*q)()=f;return p-q;}'

echo 'All pointer-arithmetic tests passed!'
