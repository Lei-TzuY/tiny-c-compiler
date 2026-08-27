#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-static-address.c
  ./minicc tmp-static-address.c > tmp-static-address.s
  cc -o tmp-static-address tmp-static-address.s
  set +e
  ./tmp-static-address
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "static address initializer test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(static address): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-static-address.c
  if ./minicc tmp-static-address.c > /dev/null 2>&1; then
    echo 'static address initializer test should have been rejected'
    echo "$input"
    exit 1
  fi
  echo 'OK(static address): rejected invalid initializer'
}

assert_run 0 'int g=17; int *p=&g; int main(){return *p==17?0:1;}'
assert_run 0 'int a[4]={3,5,7,9}; int *p=a+2; int main(){return p==&a[2]&&*p==7?0:1;}'
assert_run 0 'int a[4]; int *p=&a[3]; int main(){return p-a==3?0:1;}'
assert_run 0 'struct S{int a;int b;}; struct S s; int *p=&s.b; int main(){s.b=41;return *p==41?0:1;}'
assert_run 0 'char *p="hello"; int main(){return p[1]==101?0:1;}'
assert_run 0 'char *p="hello"+2; int main(){return p[0]==108&&p[2]==111?0:1;}'
assert_run 0 'int f(){return 23;} int (*fp)(void)=f; int main(){return fp()==23?0:1;}'
assert_run 0 'int f(){return 29;} int (*fp)(void)=&f; int main(){return fp()==29?0:1;}'
assert_run 0 'int g; int *p=1?&g:0; int main(){return p==&g?0:1;}'
assert_run 0 'int g; int *p=0?&g:0; int main(){return p==0?0:1;}'
assert_run 0 'int g; void *p=(void*)&g; int main(){return p==&g?0:1;}'
assert_run 0 'int g=8; int f(){static int *p=&g;return *p;} int main(){return f()==8?0:1;}'
assert_run 0 'int f(){static int x=9;static int *p=&x;return *p;} int main(){return f()==9?0:1;}'

# External object relocation resolves through the host linker.
printf '%s\n' 'extern int host_global; int *p=&host_global; int main(){return *p==31?0:1;}' > tmp-static-address.c
./minicc tmp-static-address.c > tmp-static-address.s
printf '%s\n' 'int host_global=31;' > tmp-static-address-helper.c
cc -c -o tmp-static-address-helper.o tmp-static-address-helper.c
cc -o tmp-static-address tmp-static-address.s tmp-static-address-helper.o
./tmp-static-address

# External function relocation resolves through the host linker.
printf '%s\n' 'extern int host_fn(void); int (*fp)(void)=host_fn; int main(){return fp()==19?0:1;}' > tmp-static-address.c
./minicc tmp-static-address.c > tmp-static-address.s
printf '%s\n' 'int host_fn(void){return 19;}' > tmp-static-address-helper.c
cc -c -o tmp-static-address-helper.o tmp-static-address-helper.c
cc -o tmp-static-address tmp-static-address.s tmp-static-address-helper.o
./tmp-static-address

assert_reject 'int f(){int x;static int *p=&x;return 0;} int main(){return f();}'
assert_reject 'int g; double *p=&g; int main(){return 0;}'
assert_reject 'int *p=(int*)123; int main(){return 0;}'
assert_reject 'int g; int n=1; int *p=&g+n; int main(){return 0;}'
assert_reject 'int *q; int *p=q; int main(){return 0;}'
assert_reject 'int g; int *p=(&g,&g); int main(){return 0;}'

rm -f tmp-static-address.c tmp-static-address.s tmp-static-address \
      tmp-static-address-helper.c tmp-static-address-helper.o

echo 'All static address initializer tests passed!'
