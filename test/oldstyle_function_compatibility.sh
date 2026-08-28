#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-oldstyle.c
  ./minicc tmp-oldstyle.c > tmp-oldstyle.s
  cc -o tmp-oldstyle tmp-oldstyle.s
  set +e
  ./tmp-oldstyle
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(old-style compatibility): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(old-style compatibility): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-oldstyle-bad.c
  if ./minicc tmp-oldstyle-bad.c > /dev/null 2>tmp-oldstyle.err; then
    echo "FAIL(old-style compatibility): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(old-style compatibility): rejected"
}

# A prototype is compatible with f() only when each parameter is unchanged by
# the default argument promotions and the prototype is not variadic.
assert_run 7 'int f(); int f(int); int f(int x){return x;} int main(void){return f(7);}'
assert_run 8 'int f(int); int f(); int f(int x){return x;} int main(void){return f(8);}'
assert_run 0 'int f(); int f(double); int f(double x){return x==9.0?0:1;} int main(void){return f(9.0);}'
assert_run 10 'int f(); int f(long); int f(long x){return x;} int main(void){return f(10);}'
assert_run 11 'int f(); int f(unsigned int); int f(unsigned int x){return x;} int main(void){return f(11);}'
assert_run 3 'int f(void); int f(){return 3;} int main(void){return f();}'
assert_run 4 'int f(){return 4;} int f(void); int main(void){return f();}'
assert_run 5 'int f(); int f(int *); int f(int *p){return *p;} int main(void){int x=5;return f(&x);}'
assert_run 6 'struct S{int x;}; int f(); int f(struct S); int f(struct S s){return s.x;} int main(void){struct S s={6};return f(s);}'
assert_run 0 'int id(int x){return x;} int main(void){int (*old)()=id;int (*proto)(int)=id;old=proto;return old(12)==12?0:1;}'
assert_run 0 'int id(int x){return x;} int main(void){int (*old)()=id;int (*proto)(int)=id;return old==proto?0:1;}'
assert_run 0 'int id(int x){return x;} int main(void){int (*old)()=id;int (*proto)(int)=id;int (*p)(int)=1?old:proto;return p(13)==13?0:1;}'
assert_run 0 'typedef int Old(); typedef int WithInt(int); int id(int x){return x;} int main(void){Old *a=id;WithInt *b=id;a=b;return a(14)==14?0:1;}'

# Moving the promotion helper into the shared type layer must not change actual
# unprototyped-call ABI behavior: float becomes double and small integers become int.
cat > tmp-oldstyle-host.c <<'EOF'
double host_fp(double x) { return x; }
int host_small(int x) { return x; }
EOF
cc -c -o tmp-oldstyle-host.o tmp-oldstyle-host.c
cat > tmp-oldstyle-interop.c <<'EOF'
double host_fp();
int host_small();
int main(void) {
  float f = 15.0;
  signed char c = 16;
  return host_fp(f) == 15.0 && host_small(c) == 16 ? 0 : 1;
}
EOF
./minicc tmp-oldstyle-interop.c > tmp-oldstyle-interop.s
cc -o tmp-oldstyle-interop tmp-oldstyle-interop.s tmp-oldstyle-host.o
./tmp-oldstyle-interop
echo 'OK(old-style compatibility): host ABI promotions'

# Types changed by default argument promotions cannot match f().
assert_reject 'int f(); int f(float); int main(void){return 0;}'
assert_reject 'int f(float); int f(); int main(void){return 0;}'
assert_reject 'int f(); int f(char); int main(void){return 0;}'
assert_reject 'int f(); int f(signed char); int main(void){return 0;}'
assert_reject 'int f(); int f(unsigned char); int main(void){return 0;}'
assert_reject 'int f(); int f(short); int main(void){return 0;}'
assert_reject 'int f(); int f(unsigned short); int main(void){return 0;}'
assert_reject 'int f(); int f(_Bool); int main(void){return 0;}'
assert_reject 'int f(); int f(int,...); int main(void){return 0;}'

# Function-pointer compatibility uses the same rule for assignment, equality,
# conditional operands, and typedef-hidden function types.
assert_reject 'int main(void){int (*a)();int (*b)(float);a=b;return 0;}'
assert_reject 'int main(void){int (*a)();int (*b)(float);return a==b;}'
assert_reject 'int main(void){int (*a)();int (*b)(float);return (1?a:b)!=0;}'
assert_reject 'typedef int Old(); typedef int WithFloat(float); int main(void){Old *a;WithFloat *b;a=b;return 0;}'

# Although an f() declaration may be compatible with a promotion-safe
# prototype, an f(){...} definition in this compiler has exactly zero
# parameters. It therefore cannot define or later acquire a nonzero prototype.
assert_reject 'int f(int); int f(){return 0;} int main(void){return 0;}'
assert_reject 'int f(double); int f(){return 0;} int main(void){return 0;}'
assert_reject 'int f(){return 0;} int f(int); int main(void){return 0;}'
assert_reject 'int f(){return 0;} int f(double); int main(void){return 0;}'
assert_reject 'int f(){return 0;} int main(void){int f(int);return 0;}'
assert_reject 'int main(void){int f(int);return 0;} int f(){return 0;}'

rm -f tmp-oldstyle.c tmp-oldstyle.s tmp-oldstyle tmp-oldstyle-bad.c tmp-oldstyle.err \
      tmp-oldstyle-host.c tmp-oldstyle-host.o tmp-oldstyle-interop.c \
      tmp-oldstyle-interop.s tmp-oldstyle-interop

echo 'All old-style function compatibility tests passed!'
