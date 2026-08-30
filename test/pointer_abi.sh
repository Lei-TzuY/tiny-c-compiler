#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

# Host-compiled callees provide an independent ABI oracle for pointer
# parameters and returns. Exercise direct/indirect calls and the seventh
# INTEGER-class argument, which is passed on the stack in SysV AMD64.
cat > tmp-pointer-host.c <<'EOF'
int host_a = 11;
int host_b = 22;

int *host_echo(int *p) { return p; }
int *host_choose(int *a, int *b) { return b ? b : a; }
int *host_seventh(int *a, int *b, int *c, int *d,
                  int *e, int *f, int *g) {
    (void)a; (void)b; (void)c; (void)d; (void)e; (void)f;
    return g;
}
EOF
cc -std=c11 -c tmp-pointer-host.c -o tmp-pointer-host.o

cat > tmp-pointer-minicc-caller.c <<'EOF'
extern int host_a;
extern int host_b;
int *host_echo(int *);
int *host_choose(int *, int *);
int *host_seventh(int *, int *, int *, int *, int *, int *, int *);

int main(void) {
    int local = 33;
    int *(*fp)(int *) = host_echo;

    if (host_echo(&local) != &local) return 1;
    if (*host_echo(&host_a) != 11) return 2;
    if (fp(&host_b) != &host_b) return 3;
    if (host_choose(&host_a, &host_b) != &host_b) return 4;
    if (host_seventh(&host_a, &host_a, &host_a, &host_a,
                     &host_a, &host_a, &local) != &local) return 5;
    if (*host_seventh(&host_a, &host_a, &host_a, &host_a,
                      &host_a, &host_a, &host_b) != 22) return 6;
    return 0;
}
EOF
"$MINICC" tmp-pointer-minicc-caller.c > tmp-pointer-minicc-caller.s
cc -o tmp-pointer-minicc-caller tmp-pointer-minicc-caller.s tmp-pointer-host.o
set +e
./tmp-pointer-minicc-caller
actual="$?"
set -e
if [ "$actual" != 0 ]; then
    echo "FAIL(pointer ABI): minicc caller -> host callee exited $actual"
    exit 1
fi

# Reverse the ABI boundary: host-compiled callers must receive minicc pointer
# returns intact and minicc callees must load register and stack parameters
# according to the platform ABI.
cat > tmp-pointer-minicc-provider.c <<'EOF'
int minicc_value = 44;

int *minicc_echo(int *p) { return p; }
int *minicc_choose(int *a, int *b) { return b ? b : a; }
int *minicc_seventh(int *a, int *b, int *c, int *d,
                    int *e, int *f, int *g) {
    return g;
}
int *minicc_global(void) { return &minicc_value; }
EOF
"$MINICC" tmp-pointer-minicc-provider.c > tmp-pointer-minicc-provider.s
cc -c tmp-pointer-minicc-provider.s -o tmp-pointer-minicc-provider.o

cat > tmp-pointer-host-caller.c <<'EOF'
extern int minicc_value;
int *minicc_echo(int *);
int *minicc_choose(int *, int *);
int *minicc_seventh(int *, int *, int *, int *, int *, int *, int *);
int *minicc_global(void);

int main(void) {
    int a = 51;
    int b = 62;
    int *(*fp)(int *) = minicc_echo;

    if (minicc_echo(&a) != &a) return 1;
    if (fp(&b) != &b) return 2;
    if (minicc_choose(&a, &b) != &b) return 3;
    if (minicc_seventh(&a, &a, &a, &a, &a, &a, &b) != &b) return 4;
    if (*minicc_seventh(&a, &a, &a, &a, &a, &a, &b) != 62) return 5;
    if (minicc_global() != &minicc_value) return 6;
    if (*minicc_global() != 44) return 7;
    return 0;
}
EOF
cc -std=c11 -o tmp-pointer-host-caller tmp-pointer-host-caller.c tmp-pointer-minicc-provider.o
set +e
./tmp-pointer-host-caller
actual="$?"
set -e
if [ "$actual" != 0 ]; then
    echo "FAIL(pointer ABI): host caller -> minicc callee exited $actual"
    exit 1
fi

rm -f tmp-pointer-host.c tmp-pointer-host.o \
      tmp-pointer-minicc-caller.c tmp-pointer-minicc-caller.s tmp-pointer-minicc-caller \
      tmp-pointer-minicc-provider.c tmp-pointer-minicc-provider.s tmp-pointer-minicc-provider.o \
      tmp-pointer-host-caller.c tmp-pointer-host-caller

echo 'All pointer ABI interoperability tests passed!'
