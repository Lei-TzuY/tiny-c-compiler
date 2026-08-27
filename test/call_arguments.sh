#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-callargs.c
  ./minicc tmp-callargs.c > tmp-callargs.s
  cc -o tmp-callargs tmp-callargs.s
  set +e
  ./tmp-callargs
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "call-argument test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(call arguments): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-callargs.c
  if ./minicc tmp-callargs.c > /dev/null 2>&1; then
    echo "call-argument test should have been rejected"
    echo "$input"
    exit 1
  fi
  echo "OK(call arguments): rejected invalid call"
}

# Fixed prototypes use the same coercion path for direct, pointer, and
# arbitrary-expression callees.
assert_run 1 'int exact(double x){return x==1.5;} int main(){return exact(1.5f);}'
assert_run 1 'int exact(double x){return x==1.5;} int main(){int (*fp)(double)=exact;return fp(1.5f);}'
assert_run 1 'int exact(double x){return x==1.5;} int main(){int (*fp)(double)=exact;return (1?fp:fp)(1.5f);}'
assert_run 7 'int add(int a,int b){return a+b;} int main(){int (*fp)(int,int)=add;return (*fp)(3,4);}'

# Arity/type diagnostics remain identical across direct and indirect forms.
assert_reject 'int f(int); int main(){return f();}'
assert_reject 'int f(int); int main(){return f(1,2);}'
assert_reject 'int f(int); int main(){int (*fp)(int)=f;return fp();}'
assert_reject 'int f(int); int main(){int (*fp)(int)=f;return (fp)(1,2);}'
assert_reject 'int f(int *); int main(){double x=1;return f(&x);}'
assert_reject 'int f(int *); int main(){int (*fp)(int *)=f;double x=1;return fp(&x);}'

# Build host helpers to observe ABI-level default promotions on unprototyped
# calls. A float argument must arrive as double; narrow integers must arrive as int.
cat > tmp-call-helper.c <<'EOF'
int promoted_double(double x) { return x == 1.5; }
int promoted_int(int x) { return x == -1; }
EOF
cc -c -o tmp-call-helper.o tmp-call-helper.c

assert_external() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-callargs.c
  ./minicc tmp-callargs.c > tmp-callargs.s
  cc -o tmp-callargs tmp-callargs.s tmp-call-helper.o
  set +e
  ./tmp-callargs
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "external call-argument test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(call arguments external): $actual"
}

assert_external 1 'int promoted_double(); int main(){return promoted_double(1.5f);}'
assert_external 1 'int promoted_double(); int main(){int (*fp)()=promoted_double;return fp(1.5f);}'
assert_external 1 'int promoted_double(); int main(){int (*fp)()=promoted_double;return (0,fp)(1.5f);}'
assert_external 1 'int promoted_int(); int main(){return promoted_int((char)-1);}'
assert_external 1 'int promoted_int(); int main(){int (*fp)()=promoted_int;return fp((short)-1);}'

rm -f tmp-call-helper.c tmp-call-helper.o

echo 'All unified call-argument tests passed!'
