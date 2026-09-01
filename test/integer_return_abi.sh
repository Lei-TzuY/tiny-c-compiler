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
EOF
./minicc tmp-intret-mini-callee.c > tmp-intret-mini-callee.s
cc -c -o tmp-intret-mini-callee.o tmp-intret-mini-callee.s

cat > tmp-intret-host-caller.c <<'EOF'
signed char mini_schar(void);
unsigned char mini_uchar(void);
short mini_short(void);
unsigned short mini_ushort(void);

int main(void) {
  if (mini_schar() != -128)
    return 1;
  if (mini_uchar() != 255)
    return 2;
  if (mini_short() != -32768)
    return 3;
  if (mini_ushort() != 65535)
    return 4;
  return 0;
}
EOF
cc -o tmp-intret-host-to-mini tmp-intret-host-caller.c tmp-intret-mini-callee.o
./tmp-intret-host-to-mini

echo 'OK(integer return ABI): host caller -> minicc callee'

# Minicc caller -> host callee: host-generated narrow returns may leave upper
# bits unspecified. Minicc must normalize/sign-extend according to the declared
# function return type for both direct and indirect calls.
cat > tmp-intret-host-callee.c <<'EOF'
signed char host_schar(void) { return 0x80; }
unsigned char host_uchar(void) { return 0x1ff; }
short host_short(void) { return 0x8000; }
unsigned short host_ushort(void) { return 0x1ffff; }
EOF
cc -c -o tmp-intret-host-callee.o tmp-intret-host-callee.c

cat > tmp-intret-mini-caller.c <<'EOF'
signed char host_schar(void);
unsigned char host_uchar(void);
short host_short(void);
unsigned short host_ushort(void);

int main(void) {
  signed char (*schar_fp)(void) = host_schar;
  unsigned short (*ushort_fp)(void) = host_ushort;

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
  return 0;
}
EOF
./minicc tmp-intret-mini-caller.c > tmp-intret-mini-caller.s
cc -o tmp-intret-mini-to-host tmp-intret-mini-caller.s tmp-intret-host-callee.o
./tmp-intret-mini-to-host

echo 'OK(integer return ABI): minicc caller -> host callee'

echo 'All narrow integer return ABI tests passed!'
