#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-control-cond.c
  ./minicc tmp-control-cond.c > tmp-control-cond.s
  cc -o tmp-control-cond tmp-control-cond.s
  set +e
  ./tmp-control-cond
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(control condition): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(control condition): $actual"
}

assert_reject_msg() {
  pattern="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-control-cond-reject.c
  if ./minicc tmp-control-cond-reject.c > /dev/null 2>tmp-control-cond.err; then
    echo "FAIL(control condition): expected rejection"
    echo "$input"
    exit 1
  fi
  if ! grep -q "$pattern" tmp-control-cond.err; then
    echo "FAIL(control condition): missing diagnostic '$pattern'"
    cat tmp-control-cond.err
    exit 1
  fi
  echo "OK(control condition): rejected with $pattern"
}

# Arithmetic, pointer, array, and function designators are valid scalar conditions.
assert_run 7 'int main(void){ int x=0; if(3) x=7; return x; }'
assert_run 5 'int main(void){ double x=0.25; if(x) return 5; return 1; }'
assert_run 6 'int main(void){ int x=1; int *p=&x; if(p) return 6; return 1; }'
assert_run 4 'int main(void){ int a[2]={1,2}; if(a) return 4; return 1; }'
assert_run 3 'int f(void){return 1;} int main(void){ if(f) return 3; return 1; }'
assert_run 4 'int main(void){ int x=0; int *p=&x; while(p){x=4;p=0;} return x; }'
assert_run 2 'int main(void){ double x=1.0; int n=0; do {n++;x=0.0;} while(x); return n+1; }'
assert_run 3 'int main(void){ int a[1]={1}; int n=0; for(;a && n<3;n++){} return n; }'
assert_run 4 'int main(void){ int n=0; for(;;){n=4;break;} return n; }'

# Records and void expressions are not scalar controlling expressions.
assert_reject_msg 'if condition must have scalar type' 'struct S{int x;}; int main(void){struct S s={1}; if(s) return 1; return 0;}'
assert_reject_msg 'if condition must have scalar type' 'union U{int x;double y;}; int main(void){union U u={1}; if(u) return 1; return 0;}'
assert_reject_msg 'if condition must have scalar type' 'int main(void){if((void)0) return 1; return 0;}'
assert_reject_msg 'while condition must have scalar type' 'struct S{int x;}; int main(void){struct S s={1}; while(s) break; return 0;}'
assert_reject_msg 'while condition must have scalar type' 'int main(void){while((void)0){} return 0;}'
assert_reject_msg 'do-while condition must have scalar type' 'struct S{int x;}; int main(void){struct S s={1}; do {} while(s); return 0;}'
assert_reject_msg 'for condition must have scalar type' 'struct S{int x;}; int main(void){struct S s={1}; for(;s;) break; return 0;}'
assert_reject_msg 'for condition must have scalar type' 'int main(void){for(;(void)0;){} return 0;}'

echo 'control-condition scalar tests passed'
