#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-static-init.c
  ./minicc tmp-static-init.c > tmp-static-init.s
  cc -o tmp-static-init tmp-static-init.s
  set +e
  ./tmp-static-init
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "static initializer test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(static initializer): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-static-init.c
  if ./minicc tmp-static-init.c > /dev/null 2>&1; then
    echo 'static initializer test should have been rejected'
    echo "$input"
    exit 1
  fi
  echo 'OK(static initializer): rejected invalid initializer'
}

# File-scope integer constant expressions.
assert_run 0 'int g=1+2*3; int main(){return g==7?0:1;}'
assert_run 0 'enum { N=7 }; int g=N*3+1; int main(){return g==22?0:1;}'
assert_run 0 'int g=(int)(3L*4); int main(){return g==12?0:1;}'
assert_run 0 'int g=(1?9:1/0); int main(){return g==9?0:1;}'
assert_run 0 'int g=(0?1/0:11); int main(){return g==11?0:1;}'
assert_run 0 'int g=((1<<5)|3)^1; int main(){return g==34?0:1;}'
assert_run 0 'int g=(5>3)&&(2<=2); int main(){return g==1?0:1;}'
assert_run 0 'unsigned long g=0xffffffffffffffffULL>>63; int main(){return g==1?0:1;}'
assert_run 0 'unsigned int g=0xffffffffU/3U; int main(){return g==1431655765U?0:1;}'
assert_run 0 'unsigned char g=300; int main(){return g==44?0:1;}'
assert_run 0 '_Bool g=5-3; int main(){return g==1?0:1;}'
assert_run 0 'int *p=1-1; int main(){return p==0?0:1;}'

# Static locals use the same evaluator and keep lexical enum visibility.
assert_run 0 'int f(){enum { N=5 }; static int x=N*4+2; return x;} int main(){return f()==22?0:1;}'
assert_run 0 'int f(){static unsigned long x=1ULL<<63; return (x>>63)==1;} int main(){return f()?0:1;}'

# Brace-enclosed static/global integer arrays now accept full constant expressions.
assert_run 0 'int a[]={1+2,1<<4,10/2}; int main(){return a[0]==3&&a[1]==16&&a[2]==5?0:1;}'
assert_run 0 'unsigned char a[]={255+1,300,7*3}; int main(){return a[0]==0&&a[1]==44&&a[2]==21?0:1;}'
assert_run 0 'int f(){static int a[]={2*3,20/4,1?8:9};return a[0]+a[1]+a[2];} int main(){return f()==19?0:1;}'

# Non-constant or semantically invalid static initializers must be diagnosed.
assert_reject 'int x=1; int g=x+1; int main(){return g;}'
assert_reject 'int f(){return 3;} int g=f(); int main(){return g;}'
assert_reject 'int g=1/0; int main(){return g;}'
assert_reject 'int g=1<<64; int main(){return g;}'
assert_reject 'int x; int g=(x=3); int main(){return g;}'
assert_reject 'int *p=123; int main(){return p!=0;}'
assert_reject 'int a[]={1,2.5}; int main(){return 0;}'

rm -f tmp-static-init.c tmp-static-init.s tmp-static-init

echo 'All static integer initializer tests passed!'
