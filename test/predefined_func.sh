#!/bin/bash
set -eu

compile_and_run() {
  cat > tmp-func.c
  ./minicc tmp-func.c > tmp-func.s
  cc -o tmp-func tmp-func.s
  ./tmp-func
  echo "OK(__func__): runtime"
}

# __func__ has the function's spelling, includes the terminating NUL in sizeof,
# and is available without a user declaration.
compile_and_run <<'EOF'
int alpha(void) {
  return sizeof __func__ == 6 && __func__[0]=='a' && __func__[4]=='a' && __func__[5]==0;
}
int main(void) {
  return alpha() && sizeof __func__ == 5 && __func__[0]=='m' && __func__[3]=='n' ? 0 : 1;
}
EOF

# One static object is shared by every use in the same function. Returning its
# decayed pointer also verifies that storage survives the function invocation.
compile_and_run <<'EOF'
const char *name(void) {
  if (__func__ != __func__) return 0;
  return __func__;
}
int main(void) {
  const char *p=name();
  return p && p[0]=='n' && p[1]=='a' && p[2]=='m' && p[3]=='e' && p[4]==0 ? 0 : 1;
}
EOF

# Distinct functions receive distinct contents and extents.
compile_and_run <<'EOF'
int short_name(void){return sizeof __func__ == 11 && __func__[0]=='s';}
int much_longer_name(void){return sizeof __func__ == 17 && __func__[5]=='l';}
int main(void){return short_name() && much_longer_name() ? 0 : 1;}
EOF

# The predefined declaration occupies the function's outer block scope, so a
# nested block may shadow it like an ordinary identifier.
compile_and_run <<'EOF'
int f(void) {
  int ok = sizeof __func__ == 2 && __func__[0]=='f';
  { int __func__ = 7; if (__func__ != 7) return 0; }
  return ok && __func__[0]=='f';
}
int main(void){return f()?0:1;}
EOF

reject() {
  cat > tmp-func-bad.c
  if ./minicc tmp-func-bad.c >/dev/null 2>&1; then
    echo "expected __func__ rejection"
    cat tmp-func-bad.c
    exit 1
  fi
  echo "OK(__func__): rejected invalid use"
}

# const char elements are not modifiable.
reject <<'EOF'
int f(void){__func__[0]='x';return 0;}
EOF

# The implicit declaration shares the function outer scope with parameters and
# declarations immediately inside the body.
reject <<'EOF'
int f(void){int __func__;return 0;}
EOF

reject <<'EOF'
int f(int __func__){return __func__;}
EOF

# There is no predefined identifier at file scope.
reject <<'EOF'
const char *p=__func__;
int main(void){return 0;}
EOF

rm -f tmp-func.c tmp-func.s tmp-func tmp-func-bad.c

echo 'All C99 __func__ tests passed!'
