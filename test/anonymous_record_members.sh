#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-anon-member.c
  ./minicc tmp-anon-member.c > tmp-anon-member.s
  cc -o tmp-anon-member tmp-anon-member.s
  set +e
  ./tmp-anon-member
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(anonymous record member): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-anon-member-bad.c
  if ./minicc tmp-anon-member-bad.c > /dev/null 2>tmp-anon-member.err; then
    echo "FAIL(anonymous record member): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Physical anonymous subobjects preserve layout while their names are promoted.
assert_run 9 'struct S{struct{int x;int y;};int z;};int main(void){struct S s={2,3,4};return s.x+s.y+s.z;}'
assert_run 7 'struct S{struct{int x;int y;};};int main(void){struct S s={3,4};struct S *p=&s;return p->x+p->y;}'
assert_run 8 'union U{struct{int x;int y;};long q;};int main(void){union U u={{3,5}};return u.x+u.y;}'
assert_run 6 'struct S{union{struct{int x;};long y;};};int main(void){struct S s={.x=6};return s.x;}'
assert_run 8 'struct S{_Alignas(8) struct{char c;};char d;};int main(void){return _Alignof(struct S);}'

# Promoted designators share the existing nested-designator machinery. Multiple
# paths into one anonymous aggregate must not zero earlier writes.
assert_run 10 'struct S{struct{int x;int y;};int z;};int main(void){struct S s={.x=2,.y=3,.z=5};return s.x+s.y+s.z;}'
assert_run 12 'struct S{union{int x;long y;};int z;};int main(void){struct S s={.x=7,.z=5};return s.x+s.z;}'
assert_run 11 'struct S{struct{int x;int y;};};static struct S s={.x=5,.y=6};int main(void){return s.x+s.y;}'
assert_run 9 'struct S{union{struct{int x;int y;};long q;};};int main(void){struct S s={.x=4,.y=5};return s.x+s.y;}'
assert_run 9 'struct S{union{struct{int x;int y;};long q;};};static struct S s={.x=4,.y=5};int main(void){return s.x+s.y;}'
assert_run 9 'struct S{struct{int x;int y;};};int main(void){return ((struct S){.x=4,.y=5}).x+((struct S){.x=4,.y=5}).y;}'

# Anonymous members remain real ABI-visible subobjects rather than flattened
# duplicate layout entries.
assert_run 7 'struct S{struct{int x;int y;};};int sum(struct S s){return s.x+s.y;}int main(void){struct S s={3,4};return sum(s);}'
assert_run 8 'struct S{char c;struct{int x;};};int main(void){return sizeof(struct S);}'

# Cross-compiler SysV ABI interoperability must classify the physical anonymous
# subobject, not the promoted logical member name. This record spans one SSE and
# one INTEGER eightbyte, so both argument and return paths exercise mixed-class
# register assignment in both directions.
cat > tmp-anon-member-host.c <<'EOF'
struct Mixed { struct { double d; }; long i; };
double host_sum(struct Mixed m){return m.d+m.i;}
struct Mixed host_make(double d,long i){struct Mixed m={.d=d,.i=i};return m;}
EOF
cc -std=c11 -c -o tmp-anon-member-host.o tmp-anon-member-host.c
cat > tmp-anon-member-mini-caller.c <<'EOF'
struct Mixed { struct { double d; }; long i; };
double host_sum(struct Mixed);
struct Mixed host_make(double,long);
int main(void){
  struct Mixed m={.d=20.0,.i=22};
  if(host_sum(m)!=42.0) return 1;
  struct Mixed r=host_make(19.0,23);
  return r.d+r.i==42.0?0:2;
}
EOF
./minicc tmp-anon-member-mini-caller.c > tmp-anon-member-mini-caller.s
cc -o tmp-anon-member-mini-caller tmp-anon-member-mini-caller.s tmp-anon-member-host.o
./tmp-anon-member-mini-caller

cat > tmp-anon-member-mini-callee.c <<'EOF'
struct Mixed { struct { double d; }; long i; };
double mini_sum(struct Mixed m){return m.d+m.i;}
struct Mixed mini_make(double d,long i){struct Mixed m={.d=d,.i=i};return m;}
EOF
./minicc tmp-anon-member-mini-callee.c > tmp-anon-member-mini-callee.s
cat > tmp-anon-member-host-main.c <<'EOF'
struct Mixed { struct { double d; }; long i; };
double mini_sum(struct Mixed);
struct Mixed mini_make(double,long);
int main(void){
  struct Mixed m={.d=20.0,.i=22};
  if(mini_sum(m)!=42.0) return 1;
  struct Mixed r=mini_make(19.0,23);
  return r.d+r.i==42.0?0:2;
}
EOF
cc -std=c11 -o tmp-anon-member-host-main tmp-anon-member-host-main.c tmp-anon-member-mini-callee.s
./tmp-anon-member-host-main

# C11 6.7.2.1p2: no-declarator member declarations are valid only for an
# untagged struct/union specifier written directly in the declaration.
assert_reject 'struct S{int;};int main(void){return 0;}'
assert_reject 'struct I{int x;};struct O{struct I;};int main(void){return 0;}'
assert_reject 'typedef struct{int x;} I;struct O{I;};int main(void){return 0;}'
assert_reject 'struct O{enum E{A};};int main(void){return 0;}'

# Promoted names inhabit the containing record member namespace recursively.
assert_reject 'struct O{struct{int x;};int x;};int main(void){return 0;}'
assert_reject 'struct O{int x;struct{int x;};};int main(void){return 0;}'
assert_reject 'struct O{struct{int x;};union{long x;int y;};};int main(void){return 0;}'
assert_reject 'struct O{struct{union{int x;long y;};};int x;};int main(void){return 0;}'

# A structure containing a flexible-array member cannot itself be embedded as
# an anonymous record member under the existing C11 FAM containment rule.
assert_reject 'struct O{struct{int n;int a[];};};int main(void){return 0;}'

rm -f tmp-anon-member.c tmp-anon-member.s tmp-anon-member \
      tmp-anon-member-bad.c tmp-anon-member.err \
      tmp-anon-member-host.c tmp-anon-member-host.o \
      tmp-anon-member-mini-caller.c tmp-anon-member-mini-caller.s tmp-anon-member-mini-caller \
      tmp-anon-member-mini-callee.c tmp-anon-member-mini-callee.s \
      tmp-anon-member-host-main.c tmp-anon-member-host-main

echo 'All C11 anonymous record-member tests passed!'
