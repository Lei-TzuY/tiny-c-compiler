#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

cat > tmp-return-host.c <<'EOF'
signed char host_schar(void) { return -3; }
short host_short(void) { return -1234; }
int host_int(void) { return -1234567; }
unsigned char host_uchar(void) { return 250; }
unsigned short host_ushort(void) { return 60000; }
unsigned int host_uint(void) { return 4000000000U; }
_Bool host_bool_false(void) { return 0; }
_Bool host_bool_true(void) { return 7; }
EOF
cc -std=c11 -c tmp-return-host.c -o tmp-return-host.o

cat > tmp-return-minicc.c <<'EOF'
signed char host_schar(void);
short host_short(void);
int host_int(void);
unsigned char host_uchar(void);
unsigned short host_ushort(void);
unsigned int host_uint(void);
_Bool host_bool_false(void);
_Bool host_bool_true(void);

signed char local_schar(void) { return -7; }
short local_short(void) { return -2222; }
int local_int(void) { return -7654321; }
_Bool local_bool_false(void) { return 0; }
_Bool local_bool_true(void) { return -9; }

int main(void) {
    if (host_schar() != -3) return 1;
    if (host_schar() >= 0) return 2;
    if (host_short() != -1234) return 3;
    if (host_short() >= 0) return 4;
    if (host_int() != -1234567) return 5;
    if (host_int() >= 0) return 6;

    if (host_uchar() != 250) return 7;
    if (host_ushort() != 60000) return 8;
    if (host_uint() != 4000000000U) return 9;

    if (local_schar() != -7) return 10;
    if (local_schar() >= 0) return 11;
    if (local_short() != -2222) return 12;
    if (local_short() >= 0) return 13;
    if (local_int() != -7654321) return 14;
    if (local_int() >= 0) return 15;

    if (host_bool_false() != 0) return 16;
    if (host_bool_true() != 1) return 17;
    if (local_bool_false() != 0) return 18;
    if (local_bool_true() != 1) return 19;
    return 0;
}
EOF

"$MINICC" tmp-return-minicc.c > tmp-return-minicc.s
cc -o tmp-return-abi tmp-return-minicc.s tmp-return-host.o
set +e
./tmp-return-abi
actual="$?"
set -e
if [ "$actual" != 0 ]; then
    echo "FAIL(function return ABI): exit $actual"
    exit 1
fi

# Verify the reverse ABI direction too: a host-compiled caller must observe
# minicc-generated narrow integer results with the correct signedness and width.
cat > tmp-return-narrow-provider.c <<'EOF'
signed char minicc_schar(void) { return -5; }
unsigned char minicc_uchar(void) { return 251; }
short minicc_short(void) { return -2345; }
unsigned short minicc_ushort(void) { return 54321; }
int minicc_int(void) { return -123456789; }
unsigned int minicc_uint(void) { return 4000000001U; }
EOF
"$MINICC" tmp-return-narrow-provider.c > tmp-return-narrow-provider.s
cc -c tmp-return-narrow-provider.s -o tmp-return-narrow-provider.o

cat > tmp-return-narrow-caller.c <<'EOF'
signed char minicc_schar(void);
unsigned char minicc_uchar(void);
short minicc_short(void);
unsigned short minicc_ushort(void);
int minicc_int(void);
unsigned int minicc_uint(void);

int main(void) {
    if (minicc_schar() != -5) return 1;
    if (minicc_schar() >= 0) return 2;
    if (minicc_uchar() != 251) return 3;
    if (minicc_short() != -2345) return 4;
    if (minicc_short() >= 0) return 5;
    if (minicc_ushort() != 54321) return 6;
    if (minicc_int() != -123456789) return 7;
    if (minicc_int() >= 0) return 8;
    if (minicc_uint() != 4000000001U) return 9;
    return 0;
}
EOF
cc -std=c11 -o tmp-return-narrow-host tmp-return-narrow-caller.c tmp-return-narrow-provider.o
set +e
./tmp-return-narrow-host
actual="$?"
set -e
if [ "$actual" != 0 ]; then
    echo "FAIL(function return ABI): host caller observed incorrect narrow integer return (exit $actual)"
    exit 1
fi

# Verify the reverse ABI direction too: host-compiled callers must observe
# canonical 0/1 _Bool results returned by minicc-generated functions.
cat > tmp-return-bool-provider.c <<'EOF'
_Bool minicc_bool_false(void) { return 0; }
_Bool minicc_bool_true_from_int(void) { return 42; }
_Bool minicc_bool_true_from_ptr(void) { static int x; return &x; }
EOF
"$MINICC" tmp-return-bool-provider.c > tmp-return-bool-provider.s
cc -c tmp-return-bool-provider.s -o tmp-return-bool-provider.o

cat > tmp-return-bool-caller.c <<'EOF'
#include <stdbool.h>

_Bool minicc_bool_false(void);
_Bool minicc_bool_true_from_int(void);
_Bool minicc_bool_true_from_ptr(void);

int main(void) {
    if (minicc_bool_false() != false) return 1;
    if (minicc_bool_true_from_int() != true) return 2;
    if (minicc_bool_true_from_ptr() != true) return 3;
    return 0;
}
EOF
cc -std=c11 -o tmp-return-bool-host tmp-return-bool-caller.c tmp-return-bool-provider.o
set +e
./tmp-return-bool-host
actual="$?"
set -e
if [ "$actual" != 0 ]; then
    echo "FAIL(function return ABI): host caller observed non-canonical _Bool return (exit $actual)"
    exit 1
fi

# A real libc function returning a negative int exercises the same caller rule.
cat > tmp-return-libc.c <<'EOF'
int strcoll(const char *, const char *);
int main(void) { return strcoll("abc", "abd") < 0 ? 0 : 1; }
EOF
"$MINICC" tmp-return-libc.c > tmp-return-libc.s
cc -o tmp-return-libc tmp-return-libc.s
set +e
./tmp-return-libc
actual="$?"
set -e
if [ "$actual" != 0 ]; then
    echo "FAIL(function return ABI): negative libc int return was not preserved"
    exit 1
fi

rm -f tmp-return-host.c tmp-return-host.o tmp-return-minicc.c tmp-return-minicc.s tmp-return-abi \
      tmp-return-narrow-provider.c tmp-return-narrow-provider.s tmp-return-narrow-provider.o \
      tmp-return-narrow-caller.c tmp-return-narrow-host \
      tmp-return-bool-provider.c tmp-return-bool-provider.s tmp-return-bool-provider.o \
      tmp-return-bool-caller.c tmp-return-bool-host \
      tmp-return-libc.c tmp-return-libc.s tmp-return-libc

echo 'All function-return ABI tests passed!'
