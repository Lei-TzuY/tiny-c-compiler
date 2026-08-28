#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-nullptr.c
  ./minicc tmp-nullptr.c > tmp-nullptr.s
  cc -o tmp-nullptr tmp-nullptr.s
  set +e
  ./tmp-nullptr
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(null pointer constant): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(null pointer constant): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-nullptr-reject.c
  if ./minicc tmp-nullptr-reject.c > /dev/null 2>&1; then
    echo "FAIL(null pointer constant): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(null pointer constant): rejected"
}

# Assignment and initialization accept any zero-valued integer constant expression.
assert_run 0 'int main(void){ int *p=1-1; return p!=0; }'
assert_run 0 'int main(void){ int *p=(int)0; return p!=0; }'
assert_run 0 'int main(void){ int *p=(3*7)-(4+17); return p!=0; }'
assert_run 0 'int main(void){ int *p=1U-1U; return p!=0; }'
assert_run 0 'enum { Z=0 }; int main(void){ int *p=Z; return p!=0; }'
# PR #74 types sizeof as unsigned long; its zero result is still an ICE null constant.
assert_run 0 'int main(void){ int (*fp)(void)=sizeof(long)-8; return fp!=0; }'

# The same rule applies to return values and fixed function arguments.
assert_run 0 'int *f(void){ return 8/2-4; } int main(void){ return f()!=0; }'
assert_run 0 'int takes(int *p){ return p==0; } int main(void){ return !takes((9%3)); }'

# Equality operators recognize zero-valued ICEs in either operand position.
assert_run 0 'int main(void){ int x; int *p=&x; return (p==(6-6)) || ((7-7)==p); }'
assert_run 0 'int main(void){ int *p=0; return !((p==(5-5)) && ((12/3-4)==p)); }'

# Conditional pointer composition accepts zero ICEs on either arm.
assert_run 0 'int main(void){ int x=4; int *p=1 ? &x : (11-11); return p!=&x; }'
assert_run 0 'int main(void){ int x=4; int *p=0 ? (14-14) : &x; return p!=&x; }'
assert_run 0 'int main(void){ int x=4; int *p=1 ? &x : (0 && (1/0)); return p!=&x; }'

# Static address initialization keeps using the same evaluator.
assert_run 0 'int g; int *p=(5*5)-25; int main(void){ return p!=0; }'
assert_run 0 'int g; int main(void){ static int *p=(2<<3)-16; return p!=0; }'

# Nonconstant or nonzero integer expressions are not null pointer constants.
assert_reject 'int main(void){ int z=0; int *p=z; return 0; }'
assert_reject 'int main(void){ const int z=0; int *p=z; return 0; }'
assert_reject 'int main(void){ int *p=2-1; return 0; }'
assert_reject 'int main(void){ int *p=0; return p==(3-2); }'
assert_reject 'int main(void){ int x; int *p=1 ? &x : 1; return 0; }'
assert_reject 'int takes(int *p){return 0;} int main(void){return takes(1);}'
assert_reject 'int *f(void){ return 1; } int main(void){ return 0; }'
assert_reject 'int main(void){ int *p=0.0; return 0; }'
assert_reject 'int main(void){ int *p=(0,0); return 0; }'
assert_reject 'int zero(void){return 0;} int main(void){ int *p=zero(); return 0; }'

# Existing integer-constant diagnostics still fire through the shared evaluator.
assert_reject 'int main(void){ int *p=1/0; return 0; }'
assert_reject 'int main(void){ int *p=1<<64; return 0; }'

echo "All null pointer constant tests passed!"
