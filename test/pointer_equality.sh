#!/bin/bash
set -eu

compile_and_run() {
  cat > tmp-pointer-equality.c
  ./minicc tmp-pointer-equality.c > tmp-pointer-equality.s
  cc -o tmp-pointer-equality tmp-pointer-equality.s
  ./tmp-pointer-equality
}

compile_and_run <<'EOF'
int f(int x) { return x; }
int g(int x) { return x + 1; }

int main(void) {
  int x = 3;
  int *p = &x;
  const int *cp = p;
  volatile int *vpq = p;
  void *vp = p;
  int a[2] = {0, 0};
  int (*fp)(int) = f;

  if (!(p == cp)) return 1;
  if (!(p == vpq)) return 2;
  if (!(vp == p)) return 3;
  if (!(p == vp)) return 4;
  if (!(a == &a[0])) return 5;
  if (!(f == fp)) return 6;
  if (!(f != g)) return 7;
  return 0;
}
EOF

reject() {
  printf '%s
' "$1" > tmp-pointer-equality-bad.c
  if ./minicc tmp-pointer-equality-bad.c >/dev/null 2>&1; then
    echo "expected incompatible pointer equality rejection: $1"
    exit 1
  fi
}

reject 'int main(void){int *p=0; double *q=0; return p==q;}'
reject 'int main(void){struct A{int x;}; struct B{int x;}; struct A *p=0; struct B *q=0; return p!=q;}'
reject 'int f(int x){return x;} double g(int x){return x;} int main(void){return f==g;}'
reject 'int main(void){int **p=0; const int **q=0; return p==q;}'
reject 'int f(void){return 0;} int main(void){void *p=0; return p==f;}'

rm -f tmp-pointer-equality.c tmp-pointer-equality.s tmp-pointer-equality       tmp-pointer-equality-bad.c

echo 'All pointer equality compatibility tests passed!'
