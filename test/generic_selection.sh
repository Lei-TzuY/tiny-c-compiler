#!/bin/bash
set -eu

compile_and_run() {
  cat > tmp-generic.c
  ./minicc tmp-generic.c > tmp-generic.s
  cc -o tmp-generic tmp-generic.s
  ./tmp-generic
  echo "OK(_Generic): runtime case"
}

# Scalar, pointer, aggregate, typedef and default selection.
compile_and_run <<'EOF'
typedef unsigned long ULong;
struct Pair { int a; long b; };
#define KIND(x) _Generic((x), int: 1, long: 2, double: 3, int *: 4, struct Pair: 5, ULong: 6, default: 9)
int main(void) {
  int i=0, *p=&i; long l=0; double d=0; struct Pair s={1,2}; ULong u=0;
  return !(KIND(i)==1 && KIND(l)==2 && KIND(d)==3 && KIND(p)==4 &&
           KIND(s)==5 && KIND(u)==6 && KIND((short)0)==9);
}
EOF

# The controlling expression is not evaluated.
compile_and_run <<'EOF'
int main(void) {
  int x=3;
  int k=_Generic(x++, int: 11, default: 22);
  return !(k==11 && x==3);
}
EOF

# Generic selection preserves the value category of the selected expression.
compile_and_run <<'EOF'
int main(void) {
  int tag=0, a=1, b=2;
  _Generic(tag, int: a, default: b)=42;
  return !(a==42 && b==2);
}
EOF

# The selected expression's type participates normally in surrounding typing.
compile_and_run <<'EOF'
int main(void) {
  int i=0;
  double x=_Generic(i, int: 1.25, default: 9);
  long y=_Generic(i, int: 40L, default: 1) + 2;
  return !(x==1.25 && y==42);
}
EOF

# Nested selections and default before a typed association.
compile_and_run <<'EOF'
int main(void) {
  long x=0;
  int v=_Generic(x, default: 1, long: _Generic(3.0, double: 42, default: 0));
  return v==42 ? 0 : 1;
}
EOF


# The controlling expression is in a value context even though it is not
# evaluated: arrays and function designators decay to pointers.
compile_and_run <<'EOF'
int main(void) {
  int a[2]={1,2};
  return _Generic(a, int *: 0, default: 1);
}
EOF

compile_and_run <<'EOF'
int main(void) {
  const int a[2]={1,2};
  return _Generic(a, const int *: 0, int *: 1, default: 2);
}
EOF

compile_and_run <<'EOF'
int main(void) {
  return _Generic("abc", char *: 0, default: 1);
}
EOF

compile_and_run <<'EOF'
int f(void){return 1;}
int main(void) {
  return _Generic(f, int (*)(void): 0, default: 1);
}
EOF

compile_and_run <<'EOF'
int f(void){return 1;}
int main(void) {
  int (*fp)(void)=f;
  return _Generic(*fp, int (*)(void): 0, default: 1);
}
EOF

# Value conversion removes only top-level qualifiers from the controlling
# expression. Qualified pointed-to types remain distinct.
compile_and_run <<'EOF'
int main(void) {
  const int x=0;
  return _Generic(x, int: 0, const int: 1, default: 2);
}
EOF

compile_and_run <<'EOF'
int main(void) {
  volatile long x=0;
  return _Generic(x, long: 0, volatile long: 1, default: 2);
}
EOF

compile_and_run <<'EOF'
int main(void) {
  int x=0;
  int *const p=&x;
  return _Generic(p, int *: 0, int *const: 1, default: 2);
}
EOF

compile_and_run <<'EOF'
int main(void) {
  int x=0;
  int *restrict p=&x;
  return _Generic(p, int *: 0, int *restrict: 1, default: 2);
}
EOF

compile_and_run <<'EOF'
int main(void) {
  const int x=0;
  const int *p=&x;
  return _Generic(p, const int *: 0, int *: 1, default: 2);
}
EOF

reject() {
  name=$1
  shift
  cat > tmp-generic-bad.c
  if ./minicc tmp-generic-bad.c >/dev/null 2>tmp-generic.err; then
    echo "expected rejection: $name"
    exit 1
  fi
  echo "OK(_Generic reject): $name"
}

# Compatible typedef aliases cannot appear as distinct associations.
reject duplicate-compatible <<'EOF'
typedef int I;
int main(void){return _Generic(1, int:1, I:2);}
EOF

reject duplicate-default <<'EOF'
int main(void){return _Generic(1, default:1, default:2);}
EOF

reject no-match <<'EOF'
int main(void){return _Generic(1.0, int:1, long:2);}
EOF

reject incomplete-association <<'EOF'
struct F;
int main(void){return _Generic(1, struct F:1, default:0);}
EOF

reject void-association <<'EOF'
int main(void){return _Generic(1, void:1, default:0);}
EOF

reject function-association <<'EOF'
int main(void){return _Generic(1, int(void):1, default:0);}
EOF

reject missing-association <<'EOF'
int main(void){return _Generic(1, );}
EOF

rm -f tmp-generic.c tmp-generic.s tmp-generic tmp-generic-bad.c tmp-generic.err

echo 'All C11 _Generic tests passed!'
