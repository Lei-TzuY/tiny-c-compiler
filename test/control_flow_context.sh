#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-control-flow.c
  ./minicc tmp-control-flow.c > tmp-control-flow.s
  cc -o tmp-control-flow tmp-control-flow.s
  set +e
  ./tmp-control-flow
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(control flow): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(control flow): $actual"
}

assert_reject_msg() {
  pattern="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-control-flow-reject.c
  if ./minicc tmp-control-flow-reject.c > /dev/null 2>tmp-control-flow.err; then
    echo "FAIL(control flow): expected rejection"
    echo "$input"
    exit 1
  fi
  if ! grep -q "$pattern" tmp-control-flow.err; then
    echo "FAIL(control flow): missing diagnostic '$pattern'"
    cat tmp-control-flow.err
    exit 1
  fi
  echo "OK(control flow): rejected with $pattern"
}

assert_run 7 'int main(void){int x=0; while(1){x=7; break;} return x;}'
assert_run 4 'int main(void){int s=0; for(int i=0;i<5;i++){if(i%2==0) continue; s+=i;} return s;}'
assert_run 7 'int main(void){int i=0,s=0; do {i++; if(i<3) continue; s+=i;} while(i<4); return s;}'
assert_run 5 'int main(void){int x=0; switch(2){case 2:x=5;break;default:x=9;} return x;}'
assert_run 46 'int main(void){int s=0; for(int i=0;i<5;i++){switch(i){case 1:continue;case 3:break;default:s+=i;} s+=10;} return s;}'
assert_run 6 'int main(void){int s=0; for(int i=0;i<3;i++){for(int j=0;j<4;j++){if(j==2) break; s++;}} return s;}'
assert_run 3 'int main(void){int i=0; while(i<3){switch(i){case 0:i++;continue;default:i++;break;}} return i;}'
assert_run 5 'int main(void){goto done; return 1; done: return 5;}'
assert_run 6 'int main(void){int L=6; goto L; L: return L;}'
assert_run 7 'int f(void){same:return 3;} int g(void){same:return 4;} int main(void){return f()+g();}'

assert_reject_msg 'break statement not within loop or switch' 'int main(void){break;}'
assert_reject_msg 'continue statement not within loop' 'int main(void){continue;}'
assert_reject_msg 'break statement not within loop or switch' 'int main(void){if(1){break;} return 0;}'
assert_reject_msg 'continue statement not within loop' 'int main(void){switch(1){default:continue;} return 0;}'
assert_reject_msg 'continue statement not within loop' 'int main(void){{{continue;}}}'
assert_reject_msg "duplicate label 'L'" 'int main(void){L:; L:; return 0;}'
assert_reject_msg "duplicate label 'L'" 'int main(void){L:; {L:;} return 0;}'
assert_reject_msg "duplicate label 'done'" 'int main(void){goto done; done:; {done:;} return 0;}'
assert_reject_msg 'undefined label: missing' 'int main(void){goto missing; return 0;}'

echo 'All control-flow context tests passed!'
