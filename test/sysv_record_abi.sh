#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-record-abi.c
  ./minicc tmp-record-abi.c > tmp-record-abi.s
  cc -o tmp-record-abi tmp-record-abi.s
  set +e
  ./tmp-record-abi
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "record ABI failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(record ABI): $actual"
}

assert_fail() {
  input="$1"
  printf '%s\n' "$input" > tmp-record-abi-bad.c
  if ./minicc tmp-record-abi-bad.c > tmp-record-abi-bad.s 2>/dev/null; then
    echo 'record ABI unexpectedly accepted unsupported by-value shape'
    echo "$input"
    exit 1
  fi
  echo 'OK(record ABI): rejected unsupported by-value shape'
}

# One- and two-eightbyte INTEGER-class records pass and return by value.
assert_run 0 'struct S{int x;int y;};int sum(struct S s){return s.x+s.y;}int main(){struct S s={20,22};return sum(s)==42?0:1;}'
assert_run 0 'struct P{long a;long b;};long sum(struct P p){return p.a+p.b;}int main(){struct P p={19,23};return sum(p)==42?0:1;}'
assert_run 0 'struct P{long a;long b;};struct P make(long a,long b){struct P p={a,b};return p;}int main(){struct P p=make(17,25);return p.a+p.b==42?0:1;}'
assert_run 0 'struct T{int a;int b;int c;};struct T make(){struct T t={10,20,12};return t;}int main(){struct T t=make();return t.a+t.b+t.c==42?0:1;}'

# Returned aggregate values remain addressable internally for member reads and
# can feed another by-value call without accidentally passing the temp address.
assert_run 0 'struct P{long a;long b;};struct P make(){struct P p={1,41};return p;}int main(){return make().b==41?0:1;}'
assert_run 0 'struct P{long a;long b;};struct P make(){struct P p={20,22};return p;}long sum(struct P p){return p.a+p.b;}int main(){return sum(make())==42?0:1;}'

# Integer-class recursion covers nested records, integer arrays, pointers and
# integer-only unions without introducing an SSE-class special case.
assert_run 0 'struct I{int a;int b;};struct O{struct I i;long z;};long f(struct O o){return o.i.a+o.i.b+o.z;}int main(){struct O o={{10,12},20};return f(o)==42?0:1;}'
assert_run 0 'union U{long x;unsigned char b[8];};long f(union U u){return u.x;}int main(){union U u={.x=42};return f(u)==42?0:1;}'
assert_run 0 'struct P{int *p;long x;};long f(struct P s){return *s.p+s.x;}int main(){int x=20;struct P s={&x,22};return f(s)==42?0:1;}'

# Function pointers use the same direct/indirect record ABI path.
assert_run 0 'struct P{long a;long b;};long sum(struct P p){return p.a+p.b;}int main(){long (*fp)(struct P)=sum;struct P p={20,22};return fp(p)==42?0:1;}'
assert_run 0 'struct P{long a;long b;};struct P make(long a,long b){struct P p={a,b};return p;}int main(){struct P (*fp)(long,long)=make;struct P p=fp(21,21);return p.a+p.b==42?0:1;}'

# If a two-eightbyte record cannot fit the remaining GP registers, SysV reverts
# the whole aggregate to the stack; a later scalar may still consume the final
# GP register.
assert_run 0 'struct P{long a;long b;};long f(long a,long b,long c,long d,long e,struct P p,long z){return a+b+c+d+e+p.a+p.b+z;}int main(){struct P p={6,7};return f(1,2,3,4,5,p,14)==42?0:1;}'

# Minicc caller -> host GCC callee verifies the external SysV boundary.
cat > tmp-record-host.c <<'EOF'
struct Pair { long a; long b; };
long host_sum(struct Pair p) { return p.a + p.b; }
struct Pair host_make(long a, long b) { struct Pair p = {a, b}; return p; }
long host_stack(long a,long b,long c,long d,long e,struct Pair p,long z) {
  return a+b+c+d+e+p.a+p.b+z;
}
EOF
cc -c -o tmp-record-host.o tmp-record-host.c
cat > tmp-record-mini-caller.c <<'EOF'
struct Pair { long a; long b; };
long host_sum(struct Pair p);
struct Pair host_make(long a, long b);
long host_stack(long,long,long,long,long,struct Pair,long);
int main(){
  struct Pair p={20,22};
  if(host_sum(p)!=42) return 1;
  struct Pair q=host_make(19,23);
  if(q.a+q.b!=42) return 2;
  struct Pair r={6,7};
  if(host_stack(1,2,3,4,5,r,14)!=42) return 3;
  return 0;
}
EOF
./minicc tmp-record-mini-caller.c > tmp-record-mini-caller.s
cc -o tmp-record-mini-caller tmp-record-mini-caller.s tmp-record-host.o
./tmp-record-mini-caller
printf '%s\n' 'OK(record ABI): minicc caller interoperates with host GCC'

# Host GCC caller -> minicc callee verifies incoming records and RAX/RDX returns.
cat > tmp-record-mini-callee.c <<'EOF'
struct Pair { long a; long b; };
long mini_sum(struct Pair p){return p.a+p.b;}
struct Pair mini_make(long a,long b){struct Pair p={a,b};return p;}
long mini_stack(long a,long b,long c,long d,long e,struct Pair p,long z){
  return a+b+c+d+e+p.a+p.b+z;
}
EOF
./minicc tmp-record-mini-callee.c > tmp-record-mini-callee.s
cat > tmp-record-host-main.c <<'EOF'
struct Pair { long a; long b; };
long mini_sum(struct Pair);
struct Pair mini_make(long,long);
long mini_stack(long,long,long,long,long,struct Pair,long);
int main(void){
  struct Pair p={18,24};
  if(mini_sum(p)!=42) return 1;
  struct Pair q=mini_make(17,25);
  if(q.a+q.b!=42) return 2;
  struct Pair r={6,7};
  if(mini_stack(1,2,3,4,5,r,14)!=42) return 3;
  return 0;
}
EOF
cc -o tmp-record-host-main tmp-record-host-main.c tmp-record-mini-callee.s
./tmp-record-host-main
printf '%s\n' 'OK(record ABI): host GCC caller interoperates with minicc callee'

# Larger records use the SysV MEMORY class; the dedicated suite exercises the
# full sret/stack protocol while these cases guard the former rejection frontier.
assert_run 0 'struct B{long a;long b;long c;};long f(struct B x){return x.a+x.b+x.c;}int main(){struct B x={10,12,20};return f(x)==42?0:1;}'
assert_run 0 'struct B{long a;long b;long c;};struct B make(){struct B x={10,12,20};return x;}int main(){struct B x=make();return x.a+x.b+x.c==42?0:1;}'

echo 'All SysV base record ABI tests passed!'
