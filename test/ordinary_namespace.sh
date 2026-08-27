#!/bin/bash
set -eu

run_case() {
  src="$1"
  printf '%s\n' "$src" > tmp-ordinary.c
  ./minicc tmp-ordinary.c > tmp-ordinary.s
  cc -o tmp-ordinary tmp-ordinary.s
  ./tmp-ordinary
  echo "OK(ordinary namespace): $src"
}

reject_case() {
  src="$1"
  printf '%s\n' "$src" > tmp-ordinary-bad.c
  if ./minicc tmp-ordinary-bad.c >/dev/null 2>&1; then
    echo "expected ordinary-namespace rejection: $src"
    exit 1
  fi
  echo "OK(reject ordinary namespace): $src"
}

# Legal shadowing and compatible redeclarations.
run_case 'typedef int T; typedef int T; int main(void) { T x=5; return x==5 ? 0 : 1; }'
run_case 'typedef int T; int main(void) { enum { T=7 }; return T==7 ? 0 : 1; }'
run_case 'int X=4; int main(void) { typedef char X; X y=1; return sizeof(y)==1 ? 0 : 1; }'
run_case 'enum { X=3 }; int main(void) { typedef char X; X y=1; return sizeof(y)==1 ? 0 : 1; }'
run_case 'int main(void) { int x=1; { int x=2; if (x!=2) return 1; } return x==1 ? 0 : 1; }'
run_case 'int g=7; int main(void) { extern int g; extern int g; return g==7 ? 0 : 1; }'
run_case 'int helper(int); int main(void) { int helper(int); return helper(3)==4 ? 0 : 1; } int helper(int x) { return x+1; }'
run_case 'int f(int x) { { int x=3; return x; } } int main(void) { return f(1)==3 ? 0 : 1; }'

# Same-scope ordinary identifiers conflict across all kinds.
reject_case 'int main(void) { int x; int x; return 0; }'
reject_case 'int main(void) { typedef int T; int T; return 0; }'
reject_case 'int main(void) { int T; typedef int T; return 0; }'
reject_case 'int main(void) { enum { X=1 }; int X; return 0; }'
reject_case 'int main(void) { int X; enum { X=1 }; return 0; }'
reject_case 'int main(void) { typedef int X; enum { X=1 }; return 0; }'
reject_case 'int main(void) { enum { X=1 }; typedef int X; return 0; }'
reject_case 'enum { X=1, X=2 }; int main(void) { return 0; }'
reject_case 'typedef int X; int X; int main(void) { return 0; }'
reject_case 'int X; typedef int X; int main(void) { return 0; }'
reject_case 'enum { X=1 }; int X; int main(void) { return 0; }'
reject_case 'int X; enum { X=1 }; int main(void) { return 0; }'
reject_case 'typedef int F; int F(void); int main(void) { return 0; }'
reject_case 'int F(void); typedef int F; int main(void) { return 0; }'
reject_case 'enum { F=1 }; int F(void); int main(void) { return 0; }'

# Nearest ordinary binding blocks outer names of every other kind.
reject_case 'int X=3; int main(void) { typedef int X; return X; }'
reject_case 'typedef int T; int main(void) { enum { T=1 }; T x; return 0; }'
reject_case 'int main(void) { typedef int F; return F(); }'

# Parameter and block-linkage constraints.
reject_case 'int f(int x, int x); int main(void) { return 0; }'
reject_case 'int f(int x, int x) { return x; } int main(void) { return 0; }'
reject_case 'int f(int x) { int x; return x; } int main(void) { return 0; }'
reject_case 'int main(void) { int x; extern int x; return 0; }'
reject_case 'int g; int main(void) { extern long g; return 0; }'
reject_case 'int main(void) { static int f(void); return 0; }'

rm -f tmp-ordinary.c tmp-ordinary.s tmp-ordinary tmp-ordinary-bad.c

echo 'All ordinary identifier namespace tests passed!'
