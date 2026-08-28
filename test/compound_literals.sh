#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-compound.c
  ./minicc tmp-compound.c > tmp-compound.s
  cc -o tmp-compound tmp-compound.s
  set +e
  ./tmp-compound
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "compound literal test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(compound literal): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-compound.c
  if ./minicc tmp-compound.c > tmp-compound.s 2>/dev/null; then
    echo "compound literal test unexpectedly accepted invalid input"
    echo "$input"
    exit 1
  fi
  echo "OK(compound literal): rejected invalid input"
}

# Scalar literals are genuine modifiable lvalues with automatic storage.
assert_run 3 'int main(){return (int){3};}'
assert_run 7 'int main(){return ((int){3}=7);}'
assert_run 9 'int main(){int *p=&(int){4}; *p=9; return *p;}'
assert_run 12 'int main(){int i=1; int *p=&(int){i++}; return *p*10+i;}'
assert_run 4 'int main(){return sizeof((int){9});}'
assert_run 5 'int main(){return (int){5}++;}'

# Aggregate, designated, nested, union, string-array and postfix uses.
assert_run 5 'struct S{int x;int y;}; int main(){return (struct S){1,5}.y;}'
assert_run 9 'struct S{int x;int y;}; int main(){struct S *p=&(struct S){.y=7,.x=2}; return p->x+p->y;}'
assert_run 6 'struct S{int x;}; int main(){return ((struct S){.x=1}.x=6);}'
assert_run 2 'int main(){return (int[3]){1,2,3}[1];}'
assert_run 7 'int main(){return (int[4]){[2]=7}[2];}'
assert_run 8 'struct R{int a[2];}; int main(){return (struct R){.a={3,8}}.a[1];}'
assert_run 11 'union U{int x;long y;}; int main(){return (union U){.x=11}.x;}'
assert_run 98 'int main(){return (char[4]){"abc"}[1];}'
assert_run 13 'struct P{int *p;}; int main(){int x=13; return *(struct P){.p=&x}.p;}'

# Compound literal record values participate in the existing SysV ABI.
assert_run 7 'struct S{int x;int y;}; int sum(struct S s){return s.x+s.y;} int main(){return sum((struct S){3,4});}'
assert_run 6 'struct S{int x;}; struct S id(struct S s){return s;} int main(){return id((struct S){6}).x;}'

# File-scope literals have anonymous static storage and are address constants.
assert_run 7 'int *p=&(int){7}; int main(){return *p;}'
assert_run 6 'struct S{int x;}; struct S *p=&(struct S){.x=6}; int main(){return p->x;}'
assert_run 6 'int *p=(int[3]){2,4,6}; int main(){return p[2];}'
assert_run 99 'char *p=(char[4]){"abc"}; int main(){return p[2];}'
assert_run 9 'struct S{int x;int y;}; int *p=&(struct S){.x=3,.y=9}.y; int main(){return *p;}'
assert_run 4 'int *p=(int[3]){2,4,6}+1; int main(){return *p;}'
assert_run 11 'int x=11; int **p=&(int *){&x}; int main(){return **p;}'

# Qualifiers and invalid forms keep ordinary C lvalue/constant rules.
assert_reject 'int main(){(const int){3}=4; return 0;}'
assert_reject 'int main(){int x=1; return *(&(0,x));}'
assert_reject 'int main(){return (void){0};}'
assert_reject 'struct S; int main(){return ((struct S){0},0);}'
# Unknown-bound array compound literals infer their bound from the initializer.
assert_run 3 'int main(){return (int[]){1,2,3}[2];}'
assert_run 12 'int main(){return sizeof((int[]){1,2,3});}'
assert_run 9 'int main(){return (int[]){[3]=9}[3];}'
assert_run 99 'int main(){return (char[]){"abc"}[2];}'
assert_run 7 'int *p=(int[]){3,5,7}; int main(){return p[2];}'
assert_run 98 'char *p=(char[]){"abc"}; int main(){return p[1];}'
assert_reject 'int main(){return (int){1,2};}'
assert_reject 'int x=(int){3}; int main(){return x;}'
assert_reject 'int main(){static int *p=&(int){5}; return *p;}'

echo 'All compound literal tests passed!'
