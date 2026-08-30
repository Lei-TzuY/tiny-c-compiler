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

# _Bool fixed parameters must observe the scalar conversion before the ABI
# boundary, including canonical 0/1 normalization for nonzero integers and
# pointers. These same-compiler cases also exercise parameter loads in callees.
assert_run 1 'int is_one(_Bool x){return x==1;} int main(){return is_one(99);}'
assert_run 1 'int is_zero(_Bool x){return x==0;} int main(){return is_zero(0);}'
assert_run 1 'int ptr_is_one(_Bool x){return x==1;} int main(){int n=0;return ptr_is_one(&n);}'

# Arity/type diagnostics remain identical across direct and indirect forms.
assert_reject 'int f(int); int main(){return f();}'
assert_reject 'int f(int); int main(){return f(1,2);}'
assert_reject 'int f(int); int main(){int (*fp)(int)=f;return fp();}'
assert_reject 'int f(int); int main(){int (*fp)(int)=f;return (fp)(1,2);}'
assert_reject 'int f(int *); int main(){double x=1;return f(&x);}'
assert_reject 'int f(int *); int main(){int (*fp)(int *)=f;double x=1;return fp(&x);}'

# Build host helpers to observe ABI-level fixed-parameter conversions and
# default promotions on unprototyped calls. A fixed _Bool argument must arrive
# canonically as 0 or 1; a variadic-style float must arrive as double, and
# narrow integers must arrive as int.
cat > tmp-call-helper.c <<'EOF'
int fixed_bool_is_one(_Bool x) { return x == 1; }
int fixed_bool_is_zero(_Bool x) { return x == 0; }
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

# Cross the minicc -> host ABI boundary so caller and callee cannot accidentally
# agree on the same incorrect _Bool representation.
assert_external 1 'int fixed_bool_is_one(_Bool); int main(){return fixed_bool_is_one(42);}'
assert_external 1 'int fixed_bool_is_zero(_Bool); int main(){return fixed_bool_is_zero(0);}'
assert_external 1 'int fixed_bool_is_one(_Bool); int main(){int x=0;return fixed_bool_is_one(&x);}'
assert_external 1 'int fixed_bool_is_one(_Bool); int main(){int (*fp)(_Bool)=fixed_bool_is_one;return fp(-7);}'

assert_external 1 'int promoted_double(); int main(){return promoted_double(1.5f);}'
assert_external 1 'int promoted_double(); int main(){int (*fp)()=promoted_double;return fp(1.5f);}'
assert_external 1 'int promoted_double(); int main(){int (*fp)()=promoted_double;return (0,fp)(1.5f);}'
assert_external 1 'int promoted_int(); int main(){return promoted_int((char)-1);}'
assert_external 1 'int promoted_int(); int main(){int (*fp)()=promoted_int;return fp((short)-1);}'

rm -f tmp-call-helper.c tmp-call-helper.o

echo 'All unified call-argument tests passed!'
