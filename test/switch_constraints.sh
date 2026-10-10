#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-switch.c
  "$MINICC" tmp-switch.c > tmp-switch.s
  cc -o tmp-switch tmp-switch.s
  set +e
  ./tmp-switch
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "switch constraint failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(switch constraint): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-switch-bad.c
  if "$MINICC" tmp-switch-bad.c > tmp-switch-bad.s 2>/dev/null; then
    echo "switch constraint unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(switch constraint): rejected invalid program"
}

assert_vm_fail() {
  printf '%s\n' "$1" > tmp-switch-vm-bad.c
  if "$MINICC" tmp-switch-vm-bad.c > tmp-switch-vm-bad.s 2>tmp-switch-vm.err; then
    echo 'FAIL(switch VM scope): accepted a label that skips a VM declaration'
    echo "$1"
    exit 1
  fi
  if ! grep -q 'switch label enters scope of a variably modified identifier' tmp-switch-vm.err; then
    echo 'FAIL(switch VM scope): rejected for an unrelated reason'
    cat tmp-switch-vm.err
    exit 1
  fi
  echo 'OK(switch VM scope): rejected skipped declaration'
}

# Controlling expressions are integer-promoted and case labels accept the
# compiler's full integer constant-expression grammar rather than one token.
assert_run 7 'int main(){int x=3;switch(x){case 1+2:return 7;default:return 0;}}'
assert_run 8 'enum E{A=4};int main(){switch(4){case A:return 8;default:return 0;}}'
assert_run 9 'int main(){switch(5){case 1?5:6:return 9;default:return 0;}}'
assert_run 10 'int main(){switch(1){case (unsigned char)257:return 10;default:return 0;}}'
assert_run 11 'int main(){unsigned short x=65535;switch(x){case 65535:return 11;default:return 0;}}'

# Case values are converted to the promoted controlling type.  In particular,
# -1 must match UINT_MAX for an unsigned-int switch without cmp-immediate
# sign-extension corrupting the machine comparison.
assert_run 12 'int main(){unsigned int x=(unsigned int)-1;switch(x){case -1:return 12;default:return 0;}}'

# The same conversion and code-generation rules must hold for 64-bit controlling
# types.  These cases exercise values that cannot be represented as signed int
# and ensure a negative case constant is compared as ULONG_MAX after conversion.
assert_run 14 'int main(){unsigned long x=4294967296UL;switch(x){case 4294967296UL:return 14;default:return 0;}}'
assert_run 15 'int main(){unsigned long x=(unsigned long)-1;switch(x){case -1:return 15;default:return 0;}}'
assert_run 16 'int main(){long x=-4294967296L;switch(x){case -4294967296L:return 16;default:return 0;}}'

# Nested switches maintain independent case/default namespaces.
assert_run 13 'int main(){int x=1;switch(x){case 1:switch(x){case 1:return 13;default:return 0;}default:return 0;}}'

# The controlling expression must have integer type.
assert_fail 'int main(){switch(1.5){case 1:return 0;}return 0;}'
assert_fail 'int main(){int x;int *p=&x;switch(p){case 0:return 0;}return 0;}'

# case/default labels are only valid while parsing a switch statement.
assert_fail 'int main(){case 1:return 0;}'
assert_fail 'int main(){default:return 0;}'

# case labels must be integer constant expressions.
assert_fail 'int main(){int x=1;switch(x){case x:return 0;}return 0;}'
assert_fail 'int main(){switch(1){case 1.5:return 0;}return 0;}'

# Duplicate values are diagnosed after constant folding and conversion to the
# promoted switch type.  A switch may contain at most one default label.
assert_fail 'int main(){switch(2){case 2:return 1;case 2:return 2;}return 0;}'
assert_fail 'int main(){switch(2){case 1+1:return 1;case 2:return 2;}return 0;}'
assert_fail 'int main(){unsigned int x=0;switch(x){case -1:return 1;case (unsigned int)-1:return 2;}return 0;}'
assert_fail 'int main(){unsigned long x=0;switch(x){case -1:return 1;case 18446744073709551615UL:return 2;}return 0;}'
assert_fail 'int main(){switch(0){default:return 1;default:return 2;}}'

# C11 6.8.4.2p2 applies to every associated label, including labels inside
# nested statements. VM pointers and typedefs count even without an allocation.
assert_vm_fail 'int main(void){int n=3;switch(1){int a[n];case 1:return 0;}}'
assert_vm_fail 'int main(void){int n=3;switch(1){int a[n];default:return 0;}}'
assert_vm_fail 'int main(void){int n=3;switch(1){int (*p)[n]=0;case 1:return 0;}}'
assert_vm_fail 'int main(void){int n=3;switch(1){int (*p)[n]=0;default:return 0;}}'
assert_vm_fail 'int main(void){int n=3;switch(1){typedef int A[n];case 1:return 0;}}'
assert_vm_fail 'int main(void){int n=3;switch(1){typedef int A[n];default:return 0;}}'
assert_vm_fail 'int main(void){int n=3;typedef int A[n];switch(1){typedef A B;case 1:return 0;}}'
assert_vm_fail 'int main(void){int n=3;switch(1){{{int a[n];case 1:return 0;}}}}'
assert_vm_fail 'int main(void){int n=3;switch(1){if(0){int a[n];default:return 0;}}}'
assert_vm_fail 'int main(void){int n=3;int a[n];switch(1){{int b[n];case 1:return 0;}}}'
assert_vm_fail 'int main(void){int n=3;switch(1){for(int a[n];;){case 1:return 0;}}}'
assert_vm_fail 'int main(void){int n=3;switch(1){for(int (*p)[n]=0;;){default:return 0;}}}'

# Already-active VM declarations remain legal, and only the nearest switch
# owns a label. Exited nested scopes must not leave a stale entry barrier.
assert_run 7 'int main(void){int n=3;int a[n];switch(1){case 1:a[0]=7;break;default:return 1;}return a[0];}'
assert_run 8 'int main(void){int n=3;int a[n];int (*p)[n]=&a;switch(9){case 1:return 1;default:(*p)[0]=8;}return a[0];}'
assert_run 9 'int main(void){int n=3;typedef int A[n];switch(1){case 1:{A a;a[0]=9;return a[0];}default:return 1;}}'
assert_run 10 'int main(void){int n=3;switch(1){case 1:{int a[n];switch(2){case 2:a[0]=10;break;default:return 1;}return a[0];}default:return 2;}}'
assert_run 11 'int main(void){int n=3;int out=0;switch(1){case 1:{int a[n];a[0]=5;out=a[0];}case 2:out+=6;break;default:return 1;}return out;}'
assert_run 12 'int main(void){switch(1){int a[3];case 1:return 12;default:return 1;}}'
assert_run 13 'int main(void){int n=3;int out=0;switch(1){case 1:;int a[n];a[0]=13;out=a[0];}return out;}'
assert_run 14 'int main(void){int n=3;switch(1){case 1:for(int a[n];;){a[0]=14;switch(2){case 2:return a[0];}}default:return 1;}}'

echo 'All switch-constraint tests passed!'
