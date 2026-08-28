#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-incomplete-array.c
  ./minicc tmp-incomplete-array.c > tmp-incomplete-array.s
  cc -o tmp-incomplete-array tmp-incomplete-array.s
  set +e
  ./tmp-incomplete-array
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(incomplete/flexible array): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(incomplete/flexible array): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-incomplete-array-reject.c
  if ./minicc tmp-incomplete-array-reject.c > /dev/null 2>&1; then
    echo "FAIL(incomplete/flexible array): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(incomplete/flexible array): rejected"
}

# A valid flexible array member contributes alignment/offset but no payload size.
assert_run 0 'struct S { int n; int data[]; }; int main(void){ struct S s={7}; return sizeof(struct S)!=4 || _Alignof(struct S)!=4 || s.n!=7; }'
assert_run 0 'struct S { char tag; double values[]; }; int main(void){ return sizeof(struct S)!=8 || _Alignof(struct S)!=8; }'
# A preceding named member may appear in the same member declaration.
assert_run 0 'struct S { int n, data[]; }; int main(void){ return sizeof(struct S)!=4; }'
# Pointers to flexible-array records and pointers to incomplete arrays remain valid.
assert_run 0 'struct S { int n; int data[]; }; struct S *p; int (*q)[]; int main(void){ return sizeof(p)!=8 || sizeof(q)!=8; }'

# Unknown outer bounds are still inferred from ordinary automatic/static/global initializers.
assert_run 0 'int main(void){ int a[]={1,2,3}; return sizeof(a)!=12 || a[2]!=3; }'
assert_run 0 'int main(void){ static int a[]={4,5}; return sizeof(a)!=8 || a[1]!=5; }'
assert_run 0 'int main(void){ char s[]="abc"; return sizeof(s)!=4 || s[3]!=0; }'
assert_run 0 'int a[][2]={{1,2},{3,4}}; int main(void){ return sizeof(a)!=16 || a[1][1]!=4; }'

# The first parameter array dimension still adjusts to a pointer before completeness checks.
assert_run 0 'int pick(int a[]){ return a[1]; } int main(void){ int a[2]={2,7}; return pick(a)-7; }'
# File-scope extern incomplete arrays compose with a later complete declaration.
assert_run 0 'extern int a[]; int a[3]={1,2,3}; int main(void){ return sizeof(a)!=12 || a[2]!=3; }'

# A leftover tentative incomplete array is completed to one element for emission.
printf '%s\n' 'int tentative[]; int main(void){ tentative[0]=9; return tentative[0]-9; }' > tmp-tentative-array.c
./minicc tmp-tentative-array.c > tmp-tentative-array.s
if ! awk '/^tentative:/{seen=1; next} seen && /\.zero[[:space:]]+4/{ok=1; exit} END{exit !ok}' tmp-tentative-array.s; then
  echo 'FAIL(incomplete/flexible array): tentative incomplete array was not completed to one element'
  exit 1
fi
cc -o tmp-tentative-array tmp-tentative-array.s
./tmp-tentative-array
printf '%s\n' 'OK(incomplete/flexible array): tentative array completed to one element'

# Incomplete arrays are not zero-sized ordinary block objects.
assert_reject 'int main(void){ int a[]; return 0; }'
assert_reject 'int main(void){ static int a[]; return 0; }'
# Array elements must be complete object types.
assert_reject 'void a[3]; int main(void){ return 0; }'
assert_reject 'struct S; struct S a[2]; int main(void){ return 0; }'
assert_reject 'int a[2][]; int main(void){ return 0; }'
# _Alignof, like sizeof, requires a complete object type.
assert_reject 'int main(void){ return _Alignof(int[]); }'

# Flexible array member constraints.
assert_reject 'struct S { int data[]; }; int main(void){ return 0; }'
assert_reject 'struct S { int n; int data[]; int tail; }; int main(void){ return 0; }'
assert_reject 'struct S { int n; int data[], tail; }; int main(void){ return 0; }'
assert_reject 'union U { int n; int data[]; }; int main(void){ return 0; }'
# A record containing a flexible array member cannot itself be embedded or arrayed.
assert_reject 'struct S { int n; int data[]; }; struct T { struct S s; }; int main(void){ return 0; }'
assert_reject 'struct S { int n; int data[]; }; struct S a[2]; int main(void){ return 0; }'

# Existing positive-bound/constant-expression constraints remain enforced.
assert_reject 'int a[0]; int main(void){ return 0; }'
assert_reject 'int main(void){ int n=3; int a[n]; return 0; }'

echo 'incomplete/flexible array tests passed'
