#!/bin/bash
set -eu

cleanup() {
  rm -f tmp-enum-abi-*.c tmp-enum-abi-*.s tmp-enum-abi-*.o tmp-enum-abi-host-to-mini tmp-enum-abi-mini-to-host
}
trap cleanup EXIT

# Host caller -> minicc callee: enum parameters and returns must use the same
# integer ABI representation as the implementation's compatible enum type.
cat > tmp-enum-abi-mini-callee.c <<'EOF'
enum Code { CODE_NEG = -7, CODE_ZERO = 0, CODE_BIG = 100000 };

enum Code mini_echo(enum Code x) { return x; }
int mini_check(enum Code a, int b, int c, int d, int e, int f, enum Code g) {
  return a == CODE_NEG && b == 2 && c == 3 && d == 4 && e == 5 && f == 6 &&
         g == CODE_BIG;
}
EOF
./minicc tmp-enum-abi-mini-callee.c > tmp-enum-abi-mini-callee.s
cc -c -o tmp-enum-abi-mini-callee.o tmp-enum-abi-mini-callee.s

cat > tmp-enum-abi-host-caller.c <<'EOF'
enum Code { CODE_NEG = -7, CODE_ZERO = 0, CODE_BIG = 100000 };
enum Code mini_echo(enum Code);
int mini_check(enum Code, int, int, int, int, int, enum Code);

int main(void) {
  if (mini_echo(CODE_NEG) != CODE_NEG)
    return 1;
  if (mini_echo(CODE_BIG) != CODE_BIG)
    return 2;
  if (!mini_check(CODE_NEG, 2, 3, 4, 5, 6, CODE_BIG))
    return 3;
  return 0;
}
EOF
cc -o tmp-enum-abi-host-to-mini tmp-enum-abi-host-caller.c tmp-enum-abi-mini-callee.o
./tmp-enum-abi-host-to-mini

echo 'OK(enum ABI): host caller -> minicc callee'

# Minicc caller -> host callee verifies the opposite ABI boundary, including a
# seventh INTEGER-class argument on the stack and an indirect enum-return call.
cat > tmp-enum-abi-host-callee.c <<'EOF'
enum Code { CODE_NEG = -7, CODE_ZERO = 0, CODE_BIG = 100000 };
enum Code host_echo(enum Code x) { return x; }
int host_check(enum Code a, int b, int c, int d, int e, int f, enum Code g) {
  return a == CODE_NEG && b == 2 && c == 3 && d == 4 && e == 5 && f == 6 &&
         g == CODE_BIG;
}
EOF
cc -c -o tmp-enum-abi-host-callee.o tmp-enum-abi-host-callee.c

cat > tmp-enum-abi-mini-caller.c <<'EOF'
enum Code { CODE_NEG = -7, CODE_ZERO = 0, CODE_BIG = 100000 };
enum Code host_echo(enum Code);
int host_check(enum Code, int, int, int, int, int, enum Code);

int main(void) {
  enum Code (*fp)(enum Code) = host_echo;
  if (fp(CODE_NEG) != CODE_NEG)
    return 1;
  if (host_echo(CODE_BIG) != CODE_BIG)
    return 2;
  if (!host_check(CODE_NEG, 2, 3, 4, 5, 6, CODE_BIG))
    return 3;
  return 0;
}
EOF
./minicc tmp-enum-abi-mini-caller.c > tmp-enum-abi-mini-caller.s
cc -o tmp-enum-abi-mini-to-host tmp-enum-abi-mini-caller.s tmp-enum-abi-host-callee.o
./tmp-enum-abi-mini-to-host

echo 'OK(enum ABI): minicc caller -> host callee'

echo 'All enum ABI tests passed!'
