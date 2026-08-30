#!/bin/bash
set -eu

fail() {
  echo "FAIL(bit-fields): $*" >&2
  exit 1
}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-bitfield.c
  ./minicc tmp-bitfield.c > tmp-bitfield.s
  cc -o tmp-bitfield tmp-bitfield.s
  set +e
  ./tmp-bitfield
  actual="$?"
  set -e
  [ "$actual" = "$expected" ] || fail "expected $expected, got $actual: $input"
  echo "OK(bit-fields): $actual"
}

assert_fail() {
  input="$1"
  printf '%s\n' "$input" > tmp-bitfield-bad.c
  if ./minicc tmp-bitfield-bad.c > tmp-bitfield-bad.s 2>/dev/null; then
    fail "unexpectedly accepted: $input"
  fi
  echo "OK(bit-fields): rejected invalid declaration/expression"
}

# Basic packing, read/write and layout. GCC SysV x86-64 packs these three
# unsigned-int fields into one 32-bit allocation unit.
assert_run 0 'struct S{unsigned int a:3;unsigned int b:5;unsigned int c:10;};int main(){struct S s={0};s.a=5;s.b=17;s.c=0x155;return sizeof(s)==4&&_Alignof(struct S)==4&&s.a==5&&s.b==17&&s.c==0x155?0:1;}'

# Signed fields sign-extend from their declared width, and assignment expression
# values reflect the value actually stored after width truncation.
assert_run 0 'struct S{signed int a:3;unsigned int b:3;};int main(){struct S s={0};int x=(s.a=7);unsigned int y=(s.b=9);return x==-1&&s.a==-1&&y==1&&s.b==1?0:1;}'

# A field that does not fit in the current allocation unit starts a new unit.
assert_run 0 'struct S{unsigned int a:31;unsigned int b:2;};int main(){struct S s={0};s.a=0x3fffffff;s.b=3;return sizeof(s)==8&&s.a==0x3fffffff&&s.b==3?0:1;}'

# Smaller declared base types use smaller allocation units.
assert_run 0 'struct S{unsigned char a:4;unsigned char b:4;unsigned char c:4;};int main(){struct S s={0};s.a=10;s.b=11;s.c=12;return sizeof(s)==2&&_Alignof(struct S)==1&&s.a==10&&s.b==11&&s.c==12?0:1;}'

# Different integer base types may share a unit when the next field still fits,
# matching the ordinary GCC x86-64 layout.
assert_run 0 'struct S{unsigned char a:4;unsigned int b:4;unsigned char c:4;};int main(){struct S s={0};s.a=10;s.b=11;s.c=12;return sizeof(s)==4&&_Alignof(struct S)==4&&s.a==10&&s.b==11&&s.c==12?0:1;}'

# Zero-width unnamed fields advance to the next allocation-unit boundary but do
# not themselves raise the aggregate alignment. Non-zero unnamed fields consume
# bits while remaining absent from the initializer/member namespace.
assert_run 0 'struct Z{char c;unsigned int :0;char d;};int main(){struct Z s;return sizeof(s)==5&&_Alignof(struct Z)==1&&((char*)&s.d-(char*)&s)==4?0:1;}'
assert_run 0 'struct U{char c;unsigned int :3;char d;};int main(){struct U s;return sizeof(s)==3&&_Alignof(struct U)==1&&((char*)&s.d-(char*)&s)==2?0:1;}'
assert_run 0 'struct G{unsigned int a:3;unsigned int :2;unsigned int b:3;};int main(){struct G s={5,6};return s.a==5&&s.b==6?0:1;}'

# Union bit-fields all begin at bit zero; unnamed fields do not enlarge a union.
assert_run 0 'union U{unsigned int a:3;unsigned char b:2;};int main(){union U u={0};u.a=5;return sizeof(u)==4&&_Alignof(union U)==4&&u.a==5&&(u.b==1)?0:1;}'
assert_run 0 'union U{unsigned int :3;char c;};int main(){return sizeof(union U)==1&&_Alignof(union U)==1?0:1;}'

# Automatic positional/designated initialization, static initialization, nested
# records and arrays all lower through bit-aware stores/images.
assert_run 0 'struct S{unsigned int a:3;unsigned int :2;unsigned int b:3;};int main(){struct S s={.b=6,.a=5};return s.a==5&&s.b==6?0:1;}'
assert_run 0 'struct S{unsigned int a:3;unsigned int b:5;};static struct S s={5,17};int main(){return s.a==5&&s.b==17?0:1;}'
assert_run 0 'struct S{unsigned int a:3;unsigned int b:5;};struct W{char x;struct S s;};static struct W w={7,{.a=5,.b=17}};int main(){return w.x==7&&w.s.a==5&&w.s.b==17?0:1;}'
assert_run 0 'struct S{unsigned int a:3;unsigned int b:5;};static struct S a[2]={{1,2},{.a=5,.b=17}};int main(){return a[0].a==1&&a[0].b==2&&a[1].a==5&&a[1].b==17?0:1;}'

# All modifying lvalue paths must preserve neighboring bits.
assert_run 0 'struct S{unsigned int a:4;unsigned int b:4;};int main(){struct S s={3,9};s.a+=2;if(s.a!=5||s.b!=9)return 1;s.a++;if(s.a!=6||s.b!=9)return 2;unsigned int old=s.a++;if(old!=6||s.a!=7||s.b!=9)return 3;s.a<<=1;return s.a==14&&s.b==9?0:4;}'

# Constant-expression widths and full-width integer fields are accepted.
assert_run 0 'enum{W=3};struct S{unsigned int a:(W+1);unsigned long b:64;};int main(){struct S s={0};s.a=15;s.b=0xffffffffffffffffUL;return s.a==15&&s.b==0xffffffffffffffffUL?0:1;}'

# C constraints: only integer bit-field base types, nonnegative ICE widths no
# larger than the declared type, zero width only unnamed, no _Alignas, and a
# bit-field is not addressable nor a valid sizeof expression operand.
assert_fail 'struct S{double a:3;};int main(){return 0;}'
assert_fail 'struct S{unsigned int a:-1;};int main(){return 0;}'
assert_fail 'struct S{unsigned int a:33;};int main(){return 0;}'
assert_fail 'struct S{unsigned int a:0;};int main(){return 0;}'
assert_fail 'struct S{_Alignas(8) unsigned int a:3;};int main(){return 0;}'
assert_fail 'struct S{unsigned int a:3;};int main(){struct S s;return &s.a!=0;}'
assert_fail 'struct S{unsigned int a:3;};int main(){struct S s;return sizeof(s.a);}'
assert_fail 'int n;struct S{unsigned int a:n;};int main(){return 0;}'

# --- Host GCC ABI oracle ----------------------------------------------------
# The two compilers independently consume/produce the same record layout. This
# catches a layout/classification bug even if minicc's own load and store paths
# made the same mistake.
cat > tmp-bitfield-abi.h <<'HDR'
struct Bits { unsigned int a:3; unsigned int b:5; signed int c:6; };
int minicc_take(struct Bits);
int host_take(struct Bits);
struct Bits minicc_make(void);
struct Bits host_make(void);
HDR

cat > tmp-bitfield-minicc-callee.c <<'SRC'
#include "tmp-bitfield-abi.h"
int minicc_take(struct Bits s){return s.a==5&&s.b==17&&s.c==-7?0:11;}
struct Bits minicc_make(void){struct Bits s={.a=6,.b=19,.c=-9};return s;}
SRC
./minicc tmp-bitfield-minicc-callee.c > tmp-bitfield-minicc-callee.s
cc -c -o tmp-bitfield-minicc-callee.o tmp-bitfield-minicc-callee.s
cat > tmp-bitfield-host-caller.c <<'SRC'
#include "tmp-bitfield-abi.h"
int main(void){struct Bits s={.a=5,.b=17,.c=-7};if(minicc_take(s))return 21;struct Bits r=minicc_make();return r.a==6&&r.b==19&&r.c==-9?0:22;}
SRC
cc -std=c11 -o tmp-bitfield-host-caller tmp-bitfield-host-caller.c tmp-bitfield-minicc-callee.o
./tmp-bitfield-host-caller || fail 'host GCC caller/consumer disagrees with minicc bit-field ABI'
echo 'OK(bit-fields): host GCC -> minicc ABI'

cat > tmp-bitfield-host-callee.c <<'SRC'
#include "tmp-bitfield-abi.h"
int host_take(struct Bits s){return s.a==5&&s.b==17&&s.c==-7?0:31;}
struct Bits host_make(void){struct Bits s={.a=6,.b=19,.c=-9};return s;}
SRC
cc -std=c11 -c -o tmp-bitfield-host-callee.o tmp-bitfield-host-callee.c
cat > tmp-bitfield-minicc-caller.c <<'SRC'
#include "tmp-bitfield-abi.h"
int main(void){struct Bits s={.a=5,.b=17,.c=-7};if(host_take(s))return 41;struct Bits r=host_make();return r.a==6&&r.b==19&&r.c==-9?0:42;}
SRC
./minicc tmp-bitfield-minicc-caller.c > tmp-bitfield-minicc-caller.s
cc -o tmp-bitfield-minicc-caller tmp-bitfield-minicc-caller.s tmp-bitfield-host-callee.o
./tmp-bitfield-minicc-caller || fail 'minicc caller/consumer disagrees with host GCC bit-field ABI'
echo 'OK(bit-fields): minicc -> host GCC ABI'

echo 'All bit-field tests passed!'
