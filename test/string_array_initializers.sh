#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-strinit.c
  ./minicc tmp-strinit.c > tmp-strinit.s
  cc -o tmp-strinit tmp-strinit.s
  set +e
  ./tmp-strinit
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "string initializer failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(string initializer): $actual"
}

assert_fail() {
  input="$1"
  printf '%s\n' "$input" > tmp-strinit-bad.c
  if ./minicc tmp-strinit-bad.c > tmp-strinit-bad.s 2>/dev/null; then
    echo "string initializer unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(string initializer): rejected invalid program"
}

assert_run 1 'int main(){char s[]="abc";return sizeof(s)==4&&s[0]==97&&s[3]==0;}'
assert_run 1 'int main(){char s[4]="abc";return s[2]==99&&s[3]==0;}'
assert_run 1 'int main(){char s[3]="abc";return sizeof(s)==3&&s[2]==99;}'
assert_run 1 'int main(){char s[6]="abc";return s[3]==0&&s[4]==0&&s[5]==0;}'
assert_run 1 'int main(){unsigned char s[]="A";return sizeof(s)==2&&s[0]==65&&s[1]==0;}'
assert_run 1 'int main(){char s[]={"hi"};return sizeof(s)==3&&s[1]==105&&s[2]==0;}'
assert_run 1 'int main(){char s[]={"hi",};return sizeof(s)==3&&s[2]==0;}'
assert_run 1 'int main(){char s[]="A\0B";return sizeof(s)==4&&s[0]==65&&s[1]==0&&s[2]==66&&s[3]==0;}'
assert_run 1 'int main(){char *p="abc";return p[0]==97&&p[3]==0;}'
assert_run 1 'char g[]="abc";int main(){g[0]=120;return g[0]==120&&g[3]==0;}'
assert_run 1 'char g[6]="abc";int main(){return g[3]==0&&g[4]==0&&g[5]==0;}'
assert_run 1 'char g[3]="abc";int main(){return sizeof(g)==3&&g[2]==99;}'
assert_run 1 'char g[]={"xy"};int main(){g[1]=122;return sizeof(g)==3&&g[1]==122&&g[2]==0;}'
assert_run 1 'int main(){static char s[]="a";s[0]=98;return sizeof(s)==2&&s[0]==98&&s[1]==0;}'
assert_fail 'int main(){char s[2]="abc";return 0;}'
assert_fail 'char s[2]="abc";int main(){return 0;}'
assert_fail 'int main(){int a[]="abc";return 0;}'
assert_fail 'int a[]="abc";int main(){return 0;}'
assert_fail 'char *p="abc";int main(){return 0;}'
assert_fail 'int main(){static char *p="abc";return 0;}'
echo 'All string-array initializer tests passed!'
