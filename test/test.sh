#!/bin/bash
assert() {
  expected="$1"
  input="$2"

  printf "%s\n" "$input" > tmp.c
  "${MINICC:-./minicc}" tmp.c > tmp.s
  if [ $? -ne 0 ]; then
    echo "Compiler failed: $input"
    exit 1
  fi
  if command -v gcc >/dev/null; then
    gcc -o tmp tmp.s
  else
    as -o tmp.o tmp.s
    as -o tmp-crt0.o test/crt0.s
    ld -o tmp tmp-crt0.o tmp.o
  fi
  ./tmp
  actual="$?"

  if [ "$actual" = "$expected" ]; then
    echo "OK: $input => $actual"
  else
    echo "FAIL: $input => expected $expected, but got $actual"
    exit 1
  fi
}

# ============================================================
# Basic arithmetic
# ============================================================
assert 0 "int main() { return 0; }"
assert 42 "int main() { return 42; }"
assert 21 "int main() { return 5+20-4; }"
assert 41 "int main() { return  12 + 34 - 5 ; }"
assert 47 "int main() { return 5+6*7; }"
assert 15 "int main() { return 5*(9-6); }"
assert 4 "int main() { return (3+5)/2; }"
assert 10 "int main() { return -10+20; }"
assert 10 "int main() { return - -10; }"
assert 10 "int main() { return - - +10; }"

# ============================================================
# Comparison
# ============================================================
assert 0 "int main() { return 0==1; }"
assert 1 "int main() { return 42==42; }"
assert 1 "int main() { return 0!=1; }"
assert 0 "int main() { return 42!=42; }"
assert 1 "int main() { return 0<1; }"
assert 0 "int main() { return 1<1; }"
assert 0 "int main() { return 2<1; }"
assert 1 "int main() { return 0<=1; }"
assert 1 "int main() { return 1<=1; }"
assert 0 "int main() { return 2<=1; }"
assert 1 "int main() { return 1>0; }"
assert 0 "int main() { return 1>1; }"
assert 0 "int main() { return 1>2; }"
assert 1 "int main() { return 1>=0; }"
assert 1 "int main() { return 1>=1; }"
assert 0 "int main() { return 1>=2; }"

# ============================================================
# Logical
# ============================================================
assert 1 "int main() { return !0; }"
assert 0 "int main() { return !42; }"
assert 1 "int main() { return 2&&3; }"
assert 0 "int main() { return 0&&3; }"
assert 1 "int main() { return 0||5; }"
assert 0 "int main() { return 0||0; }"
assert 0 "int main() { return 0||1&&0; }"
assert 0 "int main() { int x=0; 0&&(x=1); return x; }"
assert 0 "int main() { int x=0; 1||(x=1); return x; }"
assert 3 "int main() { int x=0; 1&&(x=3); return x; }"
assert 3 "int main() { int x=0; 0||(x=3); return x; }"

# ============================================================
# Variables and assignments
# ============================================================
assert 3 "int main() { int a=3; return a; }"
assert 8 "int main() { int a=3; int z=5; return a+z; }"
assert 6 "int main() { int a; int b; a=b=3; return a+b; }"
assert 3 "int main() { int foo=3; return foo; }"
assert 8 "int main() { int foo123=3; int bar=5; return foo123+bar; }"
assert 8 "int main() { int x=3; x+=5; return x; }"
assert 3 "int main() { int x=8; x-=5; return x; }"
assert 15 "int main() { int x=3; x*=5; return x; }"
assert 3 "int main() { int x=15; x/=5; return x; }"
assert 8 "int main() { int x=3; return x+=5; }"
assert 4 "int main() { int x=3; return ++x; }"
assert 2 "int main() { int x=3; return --x; }"
assert 7 "int main() { int x=3; int y=x++; return x+y; }"
assert 5 "int main() { int x=3; int y=x--; return x+y; }"

# ============================================================
# If / else
# ============================================================
assert 3 "int main() { if (0) return 2; return 3; }"
assert 3 "int main() { if (1-1) return 2; return 3; }"
assert 2 "int main() { if (1) return 2; return 3; }"
assert 2 "int main() { if (2-1) return 2; return 3; }"
assert 4 "int main() { if (0) { 1; 2; return 3; } else { return 4; } }"
assert 3 "int main() { if (1) { 1; 2; return 3; } else { return 4; } }"

# ============================================================
# Loops
# ============================================================
assert 10 "int main() { int i=0; while(i<10) i=i+1; return i; }"
assert 55 "int main() { int i=0; int j=0; while(i<=10) {j=i+j; i=i+1;} return j; }"
assert 55 "int main() { int i=0; int j=0; for (i=0; i<=10; i=i+1) j=i+j; return j; }"
assert 3 "int main() { for (;;) return 3; return 5; }"

# ============================================================
# Functions
# ============================================================
assert 3 "int ret3() { return 3; } int main() { return ret3(); }"
assert 5 "int ret5() { return 5; } int main() { return ret5(); }"
assert 8 "int add(int x, int y) { return x+y; } int main() { return add(3, 5); }"
assert 3 "int sub(int x, int y) { return x-y; } int main() { return sub(5, 2); }"
assert 21 "int add6(int a, int b, int c, int d, int e, int f) { return a+b+c+d+e+f; } int main() { return add6(1,2,3,4,5,6); }"
assert 55 "int fib(int x) { if (x<=1) return x; return fib(x-1) + fib(x-2); } int main() { return fib(10); }"

# ============================================================
# Pointers and arrays
# ============================================================
assert 3 "int main() { int x=3; return *&x; }"
assert 3 "int main() { int x=3; int *y=&x; int **z=&y; return **z; }"
assert 5 "int main() { int x=3; int y=5; return *(&x+1); }"
assert 3 "int main() { int x=3; int y=5; return *(&y-1); }"
assert 5 "int main() { int x=3; int y=5; int *z=&x; return *(z+1); }"
assert 3 "int main() { int x=3; int y=5; int *z=&y; return *(z-1); }"
assert 5 "int main() { int x[2]; x[0]=3; x[1]=5; int *p=x; p++; return *p; }"
assert 5 "int main() { int x[2]; x[0]=3; x[1]=5; int *p=x; p+=1; return *p; }"
assert 3 "int main() { int x[2]; x[0]=3; x[1]=5; int *p=x+1; p--; return *p; }"

# ============================================================
# char type
# ============================================================
assert 3 "int main() { char x=3; return x; }"
assert 1 "int main() { char x=1; char y=2; return x; }"
assert 3 "int main() { char x=1; char y=2; return x+y; }"
assert 1 "int main() { char x=127; return ++x<0; }"
assert 8 "int add(char x, char y) { return x+y; } int main() { return add(3, 5); }"

# ============================================================
# Global variables
# ============================================================
assert 0 "int x; int main() { return x; }"
assert 3 "int x; int main() { x=3; return x; }"
assert 7 "int x; int y; int main() { x=3; y=4; return x+y; }"
assert 7 "int x, y; int main() { x=3; y=4; return x+y; }"
assert 0 "int x[4]; int main() { x[0]=0; x[1]=1; x[2]=2; x[3]=3; return x[0]; }"
assert 1 "int x[4]; int main() { x[0]=0; x[1]=1; x[2]=2; x[3]=3; return x[1]; }"
assert 2 "int x[4]; int main() { x[0]=0; x[1]=1; x[2]=2; x[3]=3; return x[2]; }"
assert 3 "int x[4]; int main() { x[0]=0; x[1]=1; x[2]=2; x[3]=3; return x[3]; }"

# ============================================================
# String literals
# ============================================================
assert 97 "int main() { return \"abc\"[0]; }"
assert 98 "int main() { return \"abc\"[1]; }"
assert 99 "int main() { return \"abc\"[2]; }"
assert 0 "int main() { return \"abc\"[3]; }"

# ============================================================
# Comments
# ============================================================
assert 3 "int main() { // line comment
return 3; }"
assert 5 "int main() { /* block comment */ return 5; }"
assert 7 "int main() { return /* skip */ 7; }"

# ============================================================
# Modulo
# ============================================================
assert 2 "int main() { return 10%4; }"
assert 0 "int main() { return 10%5; }"
assert 1 "int main() { return 7%3; }"

# ============================================================
# Bitwise
# ============================================================
assert 0 "int main() { return ~-1; }"
assert 254 "int main() { char x=~1; return x; }"
assert 0 "int main() { return 0 & 1; }"
assert 1 "int main() { return 3 & 1; }"
assert 5 "int main() { return 7 & 5; }"
assert 3 "int main() { return 1 | 2; }"
assert 7 "int main() { return 3 | 5; }"
assert 6 "int main() { return 3 ^ 5; }"
assert 0 "int main() { return 5 ^ 5; }"
assert 1 "int main() { return 1 ^ 0; }"
assert 8  "int main() { return 1 << 3; }"
assert 2  "int main() { return 8 >> 2; }"
assert 16 "int main() { return 4 << 2; }"
assert 3  "int main() { return 12 >> 2; }"
assert 6 "int main() { return (3 | 6) & ~1; }"
assert 2 "int main() { int x=10; return (x >> 2) & 3; }"

# ============================================================
# sizeof
# ============================================================
assert 4 "int main() { return sizeof(int); }"
assert 8 "int main() { return sizeof(long); }"
assert 1 "int main() { return sizeof(char); }"
assert 8 "int main() { return sizeof(int*); }"
assert 4 "int main() { int x; return sizeof(x); }"
assert 1 "int main() { char x; return sizeof(x); }"
assert 8 "int main() { long x; return sizeof(x); }"
assert 1 "int main() { _Bool x; return sizeof(x); }"

# ============================================================
# void functions
# ============================================================
assert 5 "void foo() {} int main() { foo(); return 5; }"
assert 5 "void foo() { return; } int main() { foo(); return 5; }"
assert 3 "void inc(int *x) { *x += 1; } int main() { int x=2; inc(&x); return x; }"

# ============================================================
# break / continue
# ============================================================
assert 3 "int main() { int i=0; while(1) { i++; if(i==3) break; } return i; }"
assert 5 "int main() { int i; for(i=0;i<10;i++) { if(i==5) break; } return i; }"
assert 5 "int main() { int s=0; int i=0; while(i<10) { i++; if(i%2==0) continue; s++; } return s; }"
assert 5 "int main() { int s=0; int i; for(i=1;i<=10;i++) { if(i%2==0) continue; s++; } return s; }"

# ============================================================
# do-while
# ============================================================
assert 10 "int main() { int i=0; do { i++; } while(i<10); return i; }"
assert 1 "int main() { int i=0; do { i++; } while(0); return i; }"
assert 3 "int main() { int i=0; do { i++; if(i==3) break; } while(1); return i; }"

# ============================================================
# Char / string escape
# ============================================================
assert 65 "int main() { return 'A'; }"
assert 97 "int main() { return 'a'; }"
assert 10 "int main() { return '\n'; }"
assert 9  "int main() { return '\t'; }"
assert 0  "int main() { return '\0'; }"
assert 92 "int main() { return '\\\\'; }"
assert 10 "int main() { char *s = \"a\nb\"; return s[1]; }"
assert 9  "int main() { char *s = \"a\tb\"; return s[1]; }"
assert 92 "int main() { char *s = \"\\\\\"; return s[0]; }"

# ============================================================
# switch / case / default
# ============================================================
assert 5 "int main() { int x=1; switch(x) { case 1: return 5; case 2: return 6; } return 0; }"
assert 6 "int main() { int x=2; switch(x) { case 1: return 5; case 2: return 6; } return 0; }"
assert 0 "int main() { int x=3; switch(x) { case 1: return 5; case 2: return 6; } return 0; }"
assert 7 "int main() { int x=3; switch(x) { case 1: return 5; default: return 7; } return 0; }"
assert 5 "int main() { int x=1; switch(x) { case 1: return 5; default: return 7; } return 0; }"
assert 3 "int main() { int x=1; int y=0; switch(x) { case 1: y++; case 2: y++; case 3: y++; } return y; }"
assert 5 "int main() { int x=0; switch(x) { case 0: x=5; break; case 1: x=9; break; } return x; }"
assert 9 "int main() { int x=1; switch(x) { case 0: x=5; break; case 1: x=9; break; } return x; }"

# ============================================================
# Ternary
# ============================================================
assert 2 "int main() { return 1 ? 2 : 3; }"
assert 3 "int main() { return 0 ? 2 : 3; }"
assert 5 "int main() { int x=1; return x ? 5 : 10; }"
assert 7 "int main() { int x=3; return x>0 ? 7 : 8; }"
assert 3 "int main() { int a=1; int b=2; int c=3; return a>b ? a : b>c ? b : c; }"

# ============================================================
# Type cast
# ============================================================
assert 1   "int main() { return (char)257; }"
assert 0   "int main() { return (char)256; }"
assert 97  "int main() { return (char)'a'; }"
assert 3   "int main() { char x=3; return (int)x; }"

# ============================================================
# enum
# ============================================================
assert 0 "int main() { enum { A, B, C }; return A; }"
assert 1 "int main() { enum { A, B, C }; return B; }"
assert 2 "int main() { enum { A, B, C }; return C; }"
assert 5 "int main() { enum { A=5, B, C }; return A; }"
assert 6 "int main() { enum { A=5, B, C }; return B; }"
assert 10 "int main() { enum color { RED=10, GREEN, BLUE }; return RED; }"
assert 11 "int main() { enum color { RED=10, GREEN, BLUE }; return GREEN; }"
assert 2  "int main() { enum { A, B, C }; int x=C; return x; }"

# ============================================================
# Compound assigns: %=, &=, |=, ^=, <<=, >>=
# ============================================================
assert 2 "int main() { int x=10; x%=4; return x; }"
assert 1 "int main() { int x=3; x&=5; return x; }"
assert 7 "int main() { int x=5; x|=3; return x; }"
assert 6 "int main() { int x=3; x^=5; return x; }"
assert 8 "int main() { int x=1; x<<=3; return x; }"
assert 2 "int main() { int x=8; x>>=2; return x; }"

# ============================================================
# Hex and octal
# ============================================================
assert 255 "int main() { return 0xff; }"
assert 16  "int main() { return 0x10; }"
assert 8   "int main() { return 010; }"
assert 7   "int main() { return 0x7; }"

# ============================================================
# struct
# ============================================================
assert 1 "int main() { struct { int x; int y; } p; p.x=1; p.y=2; return p.x; }"
assert 2 "int main() { struct { int x; int y; } p; p.x=1; p.y=2; return p.y; }"
assert 3 "int main() { struct { int x; int y; } p; p.x=1; p.y=2; return p.x+p.y; }"
assert 7 "int main() { struct { char a; int b; } s; s.a=3; s.b=4; return s.a+s.b; }"
assert 5 "int main() { struct P { int x; int y; }; struct P p; p.x=5; struct P *q=&p; return q->x; }"
assert 9 "int main() { struct S { int x; }; struct S s; s.x=9; struct S *p=&s; return p->x; }"
assert 4 "struct P { int x; int y; }; int main() { struct P p; p.x=1; p.y=3; return p.x+p.y; }"
assert 6 "struct P { int x; int y; }; int add(struct P *p) { return p->x+p->y; } int main() { struct P p; p.x=2; p.y=4; return add(&p); }"
assert 8 "int main() { struct { int x; int y; } p; return sizeof(p); }"
assert 8 "int main() { return sizeof(struct { int x; int y; }); }"
assert 3 "int main() { struct S { int x; }; struct S a; struct S b; a.x=3; b=a; return b.x; }"

# ============================================================
# typedef
# ============================================================
assert 5 "typedef int Num; int main() { Num x=5; return x; }"
assert 3 "typedef struct { int x; int y; } Point; int main() { Point p; p.x=1; p.y=2; return p.x+p.y; }"
assert 7 "typedef int Int; Int add(Int a, Int b) { return a+b; } int main() { return add(3,4); }"

# ============================================================
# long type
# ============================================================
assert 8 "int main() { long x = 100; return sizeof(x); }"
assert 100 "long f() { return 100; } int main() { return f(); }"

# ============================================================
# for-init declaration + comma operator
# ============================================================
assert 10 "int main() { int s=0; for (int i=0; i<5; i++) s+=i; return s; }"
assert 45 "int main() { int s=0; for (int i=1; i<=9; i++) s+=i; return s; }"
assert 3 "int main() { return (1, 2, 3); }"
assert 5 "int main() { int x=0; x = (1, 2, 5); return x; }"
assert 3 "int main() { int a=1; int b=2; return (a, b, a+b); }"

# ============================================================
# Block scope
# ============================================================
assert 2 "int main() { int x=2; { int x=5; } return x; }"
assert 5 "int main() { int x=2; { int x=5; return x; } }"
assert 3 "int main() { int x=1; { int x=2; { int x=3; return x; } } }"
assert 1 "int main() { int x=1; { int x=2; } { int x=3; } return x; }"
assert 10 "int main() { int s=0; for (int i=0; i<5; i++) { int t=i; s+=t; } return s; }"

# ============================================================
# goto / labels
# ============================================================
assert 5 "int main() { goto end; return 3; end: return 5; }"
assert 10 "int main() { int x=0; loop: x++; if (x<10) goto loop; return x; }"
assert 3 "int main() { int x=1; goto skip; x=99; skip: x+=2; return x; }"

# ============================================================
# Array / struct initializers
# ============================================================
assert 1 "int main() { int a[3] = {1, 2, 3}; return a[0]; }"
assert 2 "int main() { int a[3] = {1, 2, 3}; return a[1]; }"
assert 3 "int main() { int a[3] = {1, 2, 3}; return a[2]; }"
assert 6 "int main() { int a[3] = {1, 2, 3}; return a[0]+a[1]+a[2]; }"
assert 3 "int main() { int a[] = {10, 20, 30}; return sizeof(a) / sizeof(int); }"
assert 20 "int main() { int a[] = {10, 20, 30}; return a[1]; }"
assert 1 "int main() { struct { int x; int y; } p = {1, 2}; return p.x; }"
assert 2 "int main() { struct { int x; int y; } p = {1, 2}; return p.y; }"
assert 3 "int main() { struct { int x; int y; } p = {1, 2}; return p.x+p.y; }"

# ============================================================
# Global initializers
# ============================================================
assert 1 "int g[3] = {1, 2, 3}; int main() { return g[0]; }"
assert 2 "int g[3] = {1, 2, 3}; int main() { return g[1]; }"
assert 3 "int g[3] = {1, 2, 3}; int main() { return g[2]; }"
assert 6 "int g[3] = {1, 2, 3}; int main() { return g[0]+g[1]+g[2]; }"
assert 42 "int g = 42; int main() { return g; }"

# ============================================================
# Phase 6: Multi-variable declarations
# ============================================================
assert 3 "int main() { int a=1, b=2; return a+b; }"
assert 6 "int main() { int a=1, b=2, c=3; return a+b+c; }"
assert 5 "int main() { int x=5, *p=&x; return *p; }"
assert 15 "int main() { int a=1, b=2, c=3, d=4, e=5; return a+b+c+d+e; }"
assert 6 "int main() { int s=0; for (int i=0, j=0; i<4; i++, j+=i) s=j; return s; }"

# ============================================================
# Phase 7: Negative global initializers
# ============================================================
assert 5 "int g = -5; int main() { return g + 10; }"
assert 251 "int g = -5; int main() { return (char)g; }"
assert 0 "int g = -1; int main() { return g + 1; }"
assert 7 "int a[3] = {-1, 3, 5}; int main() { return a[0]+a[1]+a[2]; }"

# ============================================================
# Phase 8: String concatenation
# ============================================================
assert 104 "int main() { char *s = \"hel\" \"lo\"; return s[0]; }"
assert 108 "int main() { char *s = \"hel\" \"lo\"; return s[3]; }"
assert 111 "int main() { char *s = \"hel\" \"lo\"; return s[4]; }"
assert 0   "int main() { char *s = \"hel\" \"lo\"; return s[5]; }"
assert 97  "int main() { char *s = \"a\" \"b\" \"c\"; return s[0]; }"
assert 99  "int main() { char *s = \"a\" \"b\" \"c\"; return s[2]; }"

# ============================================================
# Phase 9: Function pointers
# ============================================================
assert 8 "int add(int a, int b) { return a+b; } int main() { int (*fp)(int,int) = add; return fp(3,5); }"
assert 2 "int sub(int a, int b) { return a-b; } int main() { int (*fp)(int,int) = sub; return fp(5,3); }"
assert 42 "int ret42() { return 42; } int main() { int (*f)() = ret42; return f(); }"
assert 15 "int mul(int a, int b) { return a*b; } int main() { int (*fp)(int,int) = mul; return fp(3,5); }"
assert 8 "int add(int x, int y) { return x+y; } int apply(int (*f)(int,int), int a, int b) { return f(a,b); } int main() { return apply(add, 3, 5); }"

# ============================================================
# Phase 10: Multi-dimensional arrays
# ============================================================
assert 6 "int main() { int a[2][3]; a[0][0]=1; a[0][1]=2; a[0][2]=3; a[1][0]=4; a[1][1]=5; a[1][2]=6; return a[1][2]; }"
assert 1 "int main() { int a[2][3]; a[0][0]=1; a[0][1]=2; a[0][2]=3; return a[0][0]; }"
assert 5 "int main() { int a[2][3]; a[0][0]=1; a[0][1]=2; a[0][2]=3; a[1][0]=4; a[1][1]=5; a[1][2]=6; return a[1][1]; }"
assert 24 "int main() { int a[2][3]; return sizeof(a); }"
assert 12 "int main() { int a[2][3]; return sizeof(a[0]); }"
assert 4 "int main() { int a[2][3]; return sizeof(a[0][0]); }"

# ============================================================
# Phase 11: static / extern
# ============================================================
assert 5 "static int x = 5; int main() { return x; }"
assert 3 "static int x = 3; int f() { return x; } int main() { return f(); }"
assert 42 "static int g = 42; static int get() { return g; } int main() { return get(); }"
assert 5 "int main() { static int x = 5; return x; }"
assert 3 "int counter() { static int c = 0; c++; return c; } int main() { counter(); counter(); return counter(); }"

# ============================================================
# Phase 12: const, _Bool, register, inline
# ============================================================
assert 5 "int main() { const int x = 5; return x; }"
assert 3 "int main() { int const y = 3; return y; }"
assert 1 "int main() { _Bool b = 42; return b; }"
assert 1 "int main() { _Bool b = 1; return b; }"
assert 0 "int main() { _Bool b = 0; return b; }"
assert 1 "int main() { _Bool b = 100; return b; }"
assert 1 "int main() { _Bool b = -1; return b; }"
assert 3 "int main() { register int x = 3; return x; }"
assert 5 "inline int f() { return 5; } int main() { return f(); }"
assert 7 "int main() { volatile int x = 7; return x; }"
assert 1 "int main() { _Bool a=1, b=0; return a && !b; }"
# ============================================================
# Phase 14: Unsigned integers & operations
# ============================================================
assert 1 "int main() { unsigned int x = 5; return x == 5; }"
assert 1 "int main() { unsigned long x = 100; return x == 100; }"
assert 1 "int main() { unsigned char c = 255; return c == 255; }"
assert 1 "int main() { unsigned int a = 1, b = 2; return a < b; }"
assert 0 "int main() { unsigned int a = 1, b = 2; return a > b; }"
assert 1 "int main() { unsigned int a = 10, b = 3; return a / b == 3; }"
assert 1 "int main() { unsigned int a = 10, b = 3; return a % b == 1; }"
assert 1 "int main() { unsigned int x = 8; return (x >> 1) == 4; }"

# ============================================================
# Phase 15: Designated initializers
# ============================================================
assert 1 "struct P { int x; int y; }; int main() { struct P p = {.x=1, .y=2}; return p.x; }"
assert 2 "struct P { int x; int y; }; int main() { struct P p = {.x=1, .y=2}; return p.y; }"
assert 5 "struct P { int x; int y; }; int main() { struct P p = {.y=5, .x=3}; return p.y; }"
assert 10 "int main() { int a[5] = {[2]=10, [0]=5}; return a[2]; }"
assert 5 "int main() { int a[5] = {[2]=10, [0]=5}; return a[0]; }"

# ============================================================
# Phase 17: Variadic functions
# ============================================================
assert 15 "#include <stdarg.h>
int sum(int count, ...) { va_list ap; va_start(ap, count); int total=0; for(int i=0;i<count;i++) total+=va_arg(ap, int); va_end(ap); return total; }
int main() { return sum(5, 1, 2, 3, 4, 5); }"

# ============================================================
# Phase 18: C Preprocessor directives
# ============================================================
assert 10 "#define FOO 10
int main() { return FOO; }"

assert 5  "#define FOO 10
#ifdef FOO
int main() { return 5; }
#else
int main() { return 0; }
#endif"

assert 7  "#ifndef BAR
int main() { return 7; }
#else
int main() { return 0; }
#endif"

assert 1  "#include <stdbool.h>
int main() { bool b = true; return b; }"

assert 1  "#include <stdarg.h>
int main() { return 1; }"

echo "All tests passed!"
