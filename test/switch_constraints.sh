#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-switch.c
  ./minicc tmp-switch.c > tmp-switch.s
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
  if ./minicc tmp-switch-bad.c > tmp-switch-bad.s 2>/dev/null; then
    echo "switch constraint unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(switch constraint): rejected invalid program"
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
assert_fail 'int main(){switch(0){default:return 1;default:return 2;}}'

echo 'All switch-constraint tests passed!'
