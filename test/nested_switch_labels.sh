#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-nested-switch.c
  ./minicc tmp-nested-switch.c > tmp-nested-switch.s
  cc -o tmp-nested-switch tmp-nested-switch.s
  set +e
  ./tmp-nested-switch
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "nested switch label failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(nested switch label): $actual"
}

# Labels may occur in nested compound statements.
assert_run 7 'int main(){int x=2;switch(x){{case 2:return 7;}default:return 1;}}'
assert_run 5 'int main(){int x=3;switch(x){{{case 3:return 5;}}}return 1;}'

# Dispatch to a case inside an if bypasses the if condition, as C labels do.
assert_run 9 'int main(){switch(1){if(0)case 1:return 9;return 2;}}'
assert_run 8 'int main(){switch(2){if(1)return 1;else case 2:return 8;}}'

# The same rule applies inside loop bodies: dispatch enters at the label.
assert_run 6 'int main(){switch(1){while(0){case 1:return 6;}return 2;}}'
assert_run 4 'int main(){switch(1){for(;0;){case 1:return 4;}return 2;}}'
assert_run 3 'int main(){switch(1){do{case 1:return 3;}while(0);return 2;}}'

# Consecutive case labels remain aliases for the same following statement.
assert_run 11 'int main(){switch(1){case 1:case 2:return 11;default:return 3;}}'
assert_run 11 'int main(){switch(2){case 1:case 2:return 11;default:return 3;}}'

# Generic labels can wrap case/default labeled statements.
assert_run 12 'int main(){switch(1){outer:case 1:return 12;default:return 2;}}'
assert_run 13 'int main(){switch(9){outer:default:return 13;case 1:return 2;}}'

# Nested switches own independent labels; the outer dispatch must not collect
# labels from the inner switch subtree.
assert_run 14 'int main(){int x=2;switch(x){case 1:switch(2){case 2:return 1;}case 2:return 14;default:return 3;}}'

# Fallthrough still follows source order after a nested label statement.
assert_run 7 'int main(){int y=0;switch(1){{case 1:y=3;}y+=4;break;default:y=9;}return y;}'

# A nested default is a valid dispatch target too.
assert_run 15 'int main(){switch(7){if(0){default:return 15;}case 1:return 2;}}'

echo 'All nested switch-label tests passed!'
