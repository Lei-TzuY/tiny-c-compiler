#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-aggregate-static.c
  ./minicc tmp-aggregate-static.c > tmp-aggregate-static.s
  cc -o tmp-aggregate-static tmp-aggregate-static.s
  set +e
  ./tmp-aggregate-static
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "aggregate static relocation failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(aggregate static relocation): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-aggregate-static.c
  if ./minicc tmp-aggregate-static.c > /dev/null 2>&1; then
    echo 'aggregate static relocation unexpectedly accepted invalid program'
    echo "$input"
    exit 1
  fi
  echo 'OK(aggregate static relocation): rejected invalid initializer'
}

assert_run 0 'int a=3,b=5; int *p[]={&a,&b}; int main(){return sizeof(p)==16&&*p[0]==3&&*p[1]==5?0:1;}'
assert_run 0 'int a[4]={2,4,6,8}; int *p[]={a,a+3}; int main(){return *p[0]==2&&*p[1]==8?0:1;}'
assert_run 0 'int x=7; int *p[4]={[2]=&x}; int main(){return p[0]==0&&p[1]==0&&p[2]==&x&&p[3]==0?0:1;}'
assert_run 0 'int x=9; int *p[]={[1+1]=&x}; int main(){return sizeof(p)==24&&p[0]==0&&p[1]==0&&p[2]==&x?0:1;}'
assert_run 0 'int f(){return 13;} int g(){return 17;} int (*fp[])(void)={f,g}; int main(){return fp[0]()==13&&fp[1]()==17?0:1;}'
assert_run 0 'char *words[]={"ab","xyz"+1}; int main(){return words[0][1]==98&&words[1][0]==121?0:1;}'
assert_run 0 'int x=11; struct C{int *p;int value;}; struct C c={&x,31}; int main(){return c.p==&x&&*c.p==11&&c.value==31?0:1;}'
assert_run 0 'int x=12; struct C{char tag;int *p;short value;}; struct C c={65,&x,123}; int main(){return c.tag==65&&c.p==&x&&c.value==123?0:1;}'
assert_run 0 'int x=14; struct C{int *p;int value;}; struct C c={.value=7,.p=&x}; int main(){return *c.p==14&&c.value==7?0:1;}'
assert_run 0 'struct C{int value;int *p;}; struct C c={.value=5}; int main(){return c.value==5&&c.p==0?0:1;}'
assert_run 0 'int x=21; struct I{int *p;int n;}; struct O{struct I inner;int *q;}; struct O o={{&x,4},&x}; int main(){return *o.inner.p==21&&o.inner.n==4&&o.q==&x?0:1;}'
assert_run 0 'int a=6,b=8; struct S{int *p[2];int n;}; struct S s={{&a,&b},3}; int main(){return *s.p[0]+*s.p[1]+s.n==17?0:1;}'
assert_run 0 'int x=23; int f(){static int *p[]={&x,0};return p[0]==&x&&p[1]==0;} int main(){return f()?0:1;}'
assert_run 0 'int x=27; int f(){static struct C{int *p;int n;} c={&x,2};return *c.p+c.n;} int main(){return f()==29?0:1;}'
assert_run 0 'struct S{char c;double d;int n;}; struct S s={65,2.5,7}; int main(){return s.c==65&&s.d>2.4&&s.d<2.6&&s.n==7?0:1;}'

# External object relocations inside one aggregate are resolved by the host linker.
printf '%s\n' 'extern int host_a,host_b; int *p[]={&host_a,&host_b}; int main(){return *p[0]==31&&*p[1]==37?0:1;}' > tmp-aggregate-static.c
./minicc tmp-aggregate-static.c > tmp-aggregate-static.s
printf '%s\n' 'int host_a=31; int host_b=37;' > tmp-aggregate-static-helper.c
cc -c -o tmp-aggregate-static-helper.o tmp-aggregate-static-helper.c
cc -o tmp-aggregate-static tmp-aggregate-static.s tmp-aggregate-static-helper.o
./tmp-aggregate-static

# External function relocation embedded in a struct is likewise link-resolved.
printf '%s\n' 'extern int host_fn(void); struct C{int (*f)(void);int n;}; struct C c={host_fn,5}; int main(){return c.f()==41&&c.n==5?0:1;}' > tmp-aggregate-static.c
./minicc tmp-aggregate-static.c > tmp-aggregate-static.s
printf '%s\n' 'int host_fn(void){return 41;}' > tmp-aggregate-static-helper.c
cc -c -o tmp-aggregate-static-helper.o tmp-aggregate-static-helper.c
cc -o tmp-aggregate-static tmp-aggregate-static.s tmp-aggregate-static-helper.o
./tmp-aggregate-static

assert_reject 'int f(){int x;static int *p[]={&x};return 0;} int main(){return f();}'
assert_reject 'int x; double *p[]={&x}; int main(){return 0;}'
assert_reject 'int n=3; int a[]={n}; int main(){return 0;}'
assert_reject 'int *p[1]={0,0}; int main(){return 0;}'
assert_reject 'int x; int *p[1]={[2]=&x}; int main(){return 0;}'
assert_reject 'struct C{int x;}; struct C c={.missing=1}; int main(){return 0;}'
assert_reject 'struct C{int x;}; struct C c={1,2}; int main(){return 0;}'

rm -f tmp-aggregate-static.c tmp-aggregate-static.s tmp-aggregate-static \
      tmp-aggregate-static-helper.c tmp-aggregate-static-helper.o

echo 'All aggregate static relocation tests passed!'
