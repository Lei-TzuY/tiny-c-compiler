#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-mixed-union-abi.c
  ./minicc tmp-mixed-union-abi.c > tmp-mixed-union-abi.s
  cc -o tmp-mixed-union-abi tmp-mixed-union-abi.s
  set +e
  ./tmp-mixed-union-abi
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "mixed-union ABI failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(mixed-union ABI): $actual"
}

assert_fail() {
  input="$1"
  printf '%s\n' "$input" > tmp-mixed-union-abi-bad.c
  if ./minicc tmp-mixed-union-abi-bad.c > tmp-mixed-union-abi-bad.s 2>/dev/null; then
    echo 'mixed-union ABI unexpectedly accepted an unsupported shape'
    echo "$input"
    exit 1
  fi
  echo 'OK(mixed-union ABI): rejected unsupported shape'
}

# INTEGER dominates an overlapping SSE member in a single SysV eightbyte.
assert_run 0 'union U{long i;double d;};long read_i(union U u){return u.i;}int main(){union U u;u.i=42;return read_i(u)==42?0:1;}'
assert_run 0 'union U{long i;double d;};union U make(long x){union U u;u.i=x;return u;}int main(){return make(42).i==42?0:1;}'

# A full-width INTEGER-only member can cover both eightbytes of a 16-byte union.
assert_run 0 'union U{long v[2];double d;};long sum(union U u){return u.v[0]+u.v[1];}int main(){union U u;u.v[0]=20;u.v[1]=22;return sum(u)==42?0:1;}'

# The same classification composes inside an enclosing INTEGER-class record.
assert_run 0 'union U{long i;double d;};struct S{union U u;long z;};long sum(struct S s){return s.u.i+s.z;}int main(){struct S s;s.u.i=20;s.z=22;return sum(s)==42?0:1;}'

# The full classifier also handles pure SSE unions and exact INTEGER-over-SSE
# merging when a narrower integer member overlaps a wider floating member.
assert_run 0 'union U{double d;};double f(union U u){return u.d;}int main(){union U u;u.d=42.0;return f(u)==42.0?0:1;}'
assert_run 0 'union U{int i;double d;};int f(union U u){return u.i;}int main(){union U u;u.i=42;return f(u)==42?0:1;}'

# Minicc caller -> host GCC callee verifies the external ABI boundary.
cat > tmp-mixed-union-host.c <<'EOF'
union U { long i; double d; };
long host_read(union U u) { return u.i; }
union U host_make(long x) { union U u; u.i=x; return u; }
EOF
cc -c -o tmp-mixed-union-host.o tmp-mixed-union-host.c
cat > tmp-mixed-union-mini-caller.c <<'EOF'
union U { long i; double d; };
long host_read(union U);
union U host_make(long);
int main(void) {
  union U u; u.i=42;
  if (host_read(u)!=42) return 1;
  union U v=host_make(37);
  return v.i==37 ? 0 : 2;
}
EOF
./minicc tmp-mixed-union-mini-caller.c > tmp-mixed-union-mini-caller.s
cc -o tmp-mixed-union-mini-caller tmp-mixed-union-mini-caller.s tmp-mixed-union-host.o
./tmp-mixed-union-mini-caller
printf '%s\n' 'OK(mixed-union ABI): minicc caller interoperates with host GCC'

# Host GCC caller -> minicc callee verifies incoming values and INTEGER returns.
cat > tmp-mixed-union-mini-callee.c <<'EOF'
union U { long i; double d; };
long mini_read(union U u){return u.i;}
union U mini_make(long x){union U u;u.i=x;return u;}
EOF
./minicc tmp-mixed-union-mini-callee.c > tmp-mixed-union-mini-callee.s
cat > tmp-mixed-union-host-main.c <<'EOF'
union U { long i; double d; };
long mini_read(union U);
union U mini_make(long);
int main(void) {
  union U u; u.i=42;
  if (mini_read(u)!=42) return 1;
  union U v=mini_make(35);
  return v.i==35 ? 0 : 2;
}
EOF
cc -o tmp-mixed-union-host-main tmp-mixed-union-host-main.c tmp-mixed-union-mini-callee.s
./tmp-mixed-union-host-main
printf '%s\n' 'OK(mixed-union ABI): host GCC caller interoperates with minicc callee'

# A union that recursively carries a flexible-array-member structure is still
# a complete union object. The flexible array contributes no bytes to sizeof,
# so the ABI class comes entirely from the fixed-size payload.
cat > tmp-fam-union-host.c <<'EOF'
struct F { int n; int data[]; };
union Carrier { struct F f; long raw; };
long host_fam_read(union Carrier u) { return u.raw; }
union Carrier host_fam_make(long x) { union Carrier u; u.raw=x; return u; }
EOF
cc -std=c11 -pedantic-errors -c -o tmp-fam-union-host.o tmp-fam-union-host.c
cat > tmp-fam-union-mini-caller.c <<'EOF'
struct F { int n; int data[]; };
union Carrier { struct F f; long raw; };
long host_fam_read(union Carrier);
union Carrier host_fam_make(long);
int main(void) {
  union Carrier u; u.raw=0x1122334455667788L;
  if (host_fam_read(u)!=0x1122334455667788L) return 1;
  union Carrier v=host_fam_make(0x0102030405060708L);
  return v.raw==0x0102030405060708L ? 0 : 2;
}
EOF
./minicc tmp-fam-union-mini-caller.c > tmp-fam-union-mini-caller.s
cc -o tmp-fam-union-mini-caller tmp-fam-union-mini-caller.s tmp-fam-union-host.o
./tmp-fam-union-mini-caller
printf '%s\n' 'OK(mixed-union ABI): FAM-carrier union minicc caller interoperates with host GCC'

cat > tmp-fam-union-mini-callee.c <<'EOF'
struct F { int n; int data[]; };
union Carrier { struct F f; long raw; };
long mini_fam_read(union Carrier u){return u.raw;}
union Carrier mini_fam_make(long x){union Carrier u;u.raw=x;return u;}
EOF
./minicc tmp-fam-union-mini-callee.c > tmp-fam-union-mini-callee.s
cat > tmp-fam-union-host-main.c <<'EOF'
struct F { int n; int data[]; };
union Carrier { struct F f; long raw; };
long mini_fam_read(union Carrier);
union Carrier mini_fam_make(long);
int main(void) {
  union Carrier u; u.raw=0x1122334455667788L;
  if (mini_fam_read(u)!=0x1122334455667788L) return 1;
  union Carrier v=mini_fam_make(0x0102030405060708L);
  return v.raw==0x0102030405060708L ? 0 : 2;
}
EOF
cc -std=c11 -pedantic-errors -o tmp-fam-union-host-main tmp-fam-union-host-main.c tmp-fam-union-mini-callee.s
./tmp-fam-union-host-main
printf '%s\n' 'OK(mixed-union ABI): FAM-carrier union host GCC caller interoperates with minicc callee'

# Repeat the external boundary check with an SSE-class FAM carrier. The zero-size
# flexible array must not force MEMORY/INTEGER classification when the fixed
# payload is a double; arguments and returns should stay in XMM registers.
cat > tmp-fam-sse-host.c <<'EOF'
struct F { double d; int data[]; };
union Carrier { struct F f; double raw; };
double host_fam_sse_read(union Carrier u) { return u.raw; }
union Carrier host_fam_sse_make(double x) { union Carrier u; u.raw=x; return u; }
EOF
cc -std=c11 -pedantic-errors -c -o tmp-fam-sse-host.o tmp-fam-sse-host.c
cat > tmp-fam-sse-mini-caller.c <<'EOF'
struct F { double d; int data[]; };
union Carrier { struct F f; double raw; };
double host_fam_sse_read(union Carrier);
union Carrier host_fam_sse_make(double);
int main(void) {
  union Carrier u; u.raw=42.5;
  if (host_fam_sse_read(u)!=42.5) return 1;
  union Carrier v=host_fam_sse_make(37.25);
  return v.raw==37.25 ? 0 : 2;
}
EOF
./minicc tmp-fam-sse-mini-caller.c > tmp-fam-sse-mini-caller.s
cc -o tmp-fam-sse-mini-caller tmp-fam-sse-mini-caller.s tmp-fam-sse-host.o
./tmp-fam-sse-mini-caller
printf '%s\n' 'OK(mixed-union ABI): SSE FAM-carrier minicc caller interoperates with host GCC'

cat > tmp-fam-sse-mini-callee.c <<'EOF'
struct F { double d; int data[]; };
union Carrier { struct F f; double raw; };
double mini_fam_sse_read(union Carrier u){return u.raw;}
union Carrier mini_fam_sse_make(double x){union Carrier u;u.raw=x;return u;}
EOF
./minicc tmp-fam-sse-mini-callee.c > tmp-fam-sse-mini-callee.s
cat > tmp-fam-sse-host-main.c <<'EOF'
struct F { double d; int data[]; };
union Carrier { struct F f; double raw; };
double mini_fam_sse_read(union Carrier);
union Carrier mini_fam_sse_make(double);
int main(void) {
  union Carrier u; u.raw=42.5;
  if (mini_fam_sse_read(u)!=42.5) return 1;
  union Carrier v=mini_fam_sse_make(35.75);
  return v.raw==35.75 ? 0 : 2;
}
EOF
cc -std=c11 -pedantic-errors -o tmp-fam-sse-host-main tmp-fam-sse-host-main.c tmp-fam-sse-mini-callee.s
./tmp-fam-sse-host-main
printf '%s\n' 'OK(mixed-union ABI): SSE FAM-carrier host GCC caller interoperates with minicc callee'

rm -f tmp-mixed-union-abi.c tmp-mixed-union-abi.s tmp-mixed-union-abi \
      tmp-mixed-union-abi-bad.c tmp-mixed-union-abi-bad.s \
      tmp-mixed-union-host.c tmp-mixed-union-host.o \
      tmp-mixed-union-mini-caller.c tmp-mixed-union-mini-caller.s tmp-mixed-union-mini-caller \
      tmp-mixed-union-mini-callee.c tmp-mixed-union-mini-callee.s \
      tmp-mixed-union-host-main.c tmp-mixed-union-host-main \
      tmp-fam-union-host.c tmp-fam-union-host.o \
      tmp-fam-union-mini-caller.c tmp-fam-union-mini-caller.s tmp-fam-union-mini-caller \
      tmp-fam-union-mini-callee.c tmp-fam-union-mini-callee.s \
      tmp-fam-union-host-main.c tmp-fam-union-host-main \
      tmp-fam-sse-host.c tmp-fam-sse-host.o \
      tmp-fam-sse-mini-caller.c tmp-fam-sse-mini-caller.s tmp-fam-sse-mini-caller \
      tmp-fam-sse-mini-callee.c tmp-fam-sse-mini-callee.s \
      tmp-fam-sse-host-main.c tmp-fam-sse-host-main

echo 'All mixed-union SysV ABI tests passed!'
