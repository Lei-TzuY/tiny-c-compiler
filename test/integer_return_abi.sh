#!/bin/bash
set -eu

cleanup() {
  rm -f tmp-intret-*.c tmp-intret-*.s tmp-intret-*.o tmp-intret-host-to-mini tmp-intret-mini-to-host
}
trap cleanup EXIT

# Host caller -> minicc callee: verify narrow integer return values carry the
# declared signedness/width across the ABI boundary. The caller must observe
# the same C value regardless of the unspecified upper bits of the return
# register.
cat > tmp-intret-mini-callee.c <<'EOF'
signed char mini_schar(void) { return 0x80; }
unsigned char mini_uchar(void) { return 0x1ff; }
short mini_short(void) { return 0x8000; }
unsigned short mini_ushort(void) { return 0x1ffff; }
int mini_int(void) { return 0x80000000U; }
unsigned int mini_uint(void) { return 0xffffffffU; }
EOF
./minicc tmp-intret-mini-callee.c > tmp-intret-mini-callee.s
cc -c -o tmp-intret-mini-callee.o tmp-intret-mini-callee.s

cat > tmp-intret-host-caller.c <<'EOF'
signed char mini_schar(void);
unsigned char mini_uchar(void);
short mini_short(void);
unsigned short mini_ushort(void);
int mini_int(void);
unsigned int mini_uint(void);

int main(void) {
  if (mini_schar() != -128)
    return 1;
  if (mini_uchar() != 255)
    return 2;
  if (mini_short() != -32768)
    return 3;
  if (mini_ushort() != 65535)
    return 4;
  if ((long)mini_int() != -2147483648L)
    return 5;
  if ((unsigned long)mini_uint() != 4294967295UL)
    return 6;
  return 0;
}
EOF
cc -o tmp-intret-host-to-mini tmp-intret-host-caller.c tmp-intret-mini-callee.o
./tmp-intret-host-to-mini

echo 'OK(integer return ABI): host caller -> minicc callee'

# Minicc caller -> host callee: host-generated narrow returns may leave upper
# bits unspecified. Minicc must normalize/sign-extend according to the declared
# function return type for both direct and indirect calls. The same rule matters
# for 32-bit returns when the expression is immediately widened to 64 bits:
# signed int must sign-extend while unsigned int must zero-extend.
cat > tmp-intret-host-callee.c <<'EOF'
signed char host_schar(void) { return 0x80; }
unsigned char host_uchar(void) { return 0x1ff; }
short host_short(void) { return 0x8000; }
unsigned short host_ushort(void) { return 0x1ffff; }
int host_int(void) { return 0x80000000U; }
unsigned int host_uint(void) { return 0xffffffffU; }
EOF
cc -c -o tmp-intret-host-callee.o tmp-intret-host-callee.c

cat > tmp-intret-mini-caller.c <<'EOF'
signed char host_schar(void);
unsigned char host_uchar(void);
short host_short(void);
unsigned short host_ushort(void);
int host_int(void);
unsigned int host_uint(void);

int main(void) {
  signed char (*schar_fp)(void) = host_schar;
  unsigned short (*ushort_fp)(void) = host_ushort;
  int (*int_fp)(void) = host_int;
  unsigned int (*uint_fp)(void) = host_uint;

  if (host_schar() != -128)
    return 1;
  if (host_uchar() != 255)
    return 2;
  if (host_short() != -32768)
    return 3;
  if (host_ushort() != 65535)
    return 4;
  if (schar_fp() != -128)
    return 5;
  if (ushort_fp() != 65535)
    return 6;
  if ((long)host_int() != -2147483648L)
    return 7;
  if ((unsigned long)host_uint() != 4294967295UL)
    return 8;
  if ((long)int_fp() != -2147483648L)
    return 9;
  if ((unsigned long)uint_fp() != 4294967295UL)
    return 10;
  return 0;
}
EOF
./minicc tmp-intret-mini-caller.c > tmp-intret-mini-caller.s
cc -o tmp-intret-mini-to-host tmp-intret-mini-caller.s tmp-intret-host-callee.o
./tmp-intret-mini-to-host

echo 'OK(integer return ABI): minicc caller -> host callee'

echo 'All integer return ABI tests passed!'
