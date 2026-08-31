#!/bin/bash
set -eu

cleanup() {
  rm -f tmp-enum-abi-*.c tmp-enum-abi-*.s tmp-enum-abi-*.o tmp-enum-abi-host-to-mini tmp-enum-abi-mini-to-host tmp-enum-abi-callback-host-to-mini tmp-enum-abi-callback-mini-to-host
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

# Host callback -> minicc indirect call: exercise enum values through a callback
# parameter and return across the compiler boundary. The seventh INTEGER-class
# argument forces the callback itself onto the overflow stack path.
cat > tmp-enum-abi-mini-callback-callee.c <<'EOF'
enum Code { CODE_NEG = -7, CODE_ZERO = 0, CODE_BIG = 100000 };

typedef enum Code (*CodeFn)(enum Code);

enum Code mini_apply(CodeFn fn, enum Code x) { return fn(x); }
int mini_apply_seventh(int a, int b, int c, int d, int e, int f,
                       CodeFn fn, enum Code x) {
  return a == 1 && b == 2 && c == 3 && d == 4 && e == 5 && f == 6 &&
         fn(x) == CODE_NEG;
}
EOF
./minicc tmp-enum-abi-mini-callback-callee.c > tmp-enum-abi-mini-callback-callee.s
cc -c -o tmp-enum-abi-mini-callback-callee.o tmp-enum-abi-mini-callback-callee.s

cat > tmp-enum-abi-host-callback-caller.c <<'EOF'
enum Code { CODE_NEG = -7, CODE_ZERO = 0, CODE_BIG = 100000 };
typedef enum Code (*CodeFn)(enum Code);
enum Code mini_apply(CodeFn, enum Code);
int mini_apply_seventh(int, int, int, int, int, int, CodeFn, enum Code);

enum Code host_to_neg(enum Code x) {
  return x == CODE_BIG ? CODE_NEG : CODE_ZERO;
}

int main(void) {
  if (mini_apply(host_to_neg, CODE_BIG) != CODE_NEG)
    return 1;
  if (!mini_apply_seventh(1, 2, 3, 4, 5, 6, host_to_neg, CODE_BIG))
    return 2;
  return 0;
}
EOF
cc -o tmp-enum-abi-callback-host-to-mini tmp-enum-abi-host-callback-caller.c tmp-enum-abi-mini-callback-callee.o
./tmp-enum-abi-callback-host-to-mini

echo 'OK(enum callback ABI): host callback -> minicc indirect call'

# Minicc callback -> host indirect call covers the reverse compiler boundary.
cat > tmp-enum-abi-host-callback-callee.c <<'EOF'
enum Code { CODE_NEG = -7, CODE_ZERO = 0, CODE_BIG = 100000 };
typedef enum Code (*CodeFn)(enum Code);

enum Code host_apply(CodeFn fn, enum Code x) { return fn(x); }
int host_apply_seventh(int a, int b, int c, int d, int e, int f,
                       CodeFn fn, enum Code x) {
  return a == 1 && b == 2 && c == 3 && d == 4 && e == 5 && f == 6 &&
         fn(x) == CODE_BIG;
}
EOF
cc -c -o tmp-enum-abi-host-callback-callee.o tmp-enum-abi-host-callback-callee.c

cat > tmp-enum-abi-mini-callback-caller.c <<'EOF'
enum Code { CODE_NEG = -7, CODE_ZERO = 0, CODE_BIG = 100000 };
typedef enum Code (*CodeFn)(enum Code);
enum Code host_apply(CodeFn, enum Code);
int host_apply_seventh(int, int, int, int, int, int, CodeFn, enum Code);

enum Code mini_to_big(enum Code x) {
  return x == CODE_NEG ? CODE_BIG : CODE_ZERO;
}

int main(void) {
  if (host_apply(mini_to_big, CODE_NEG) != CODE_BIG)
    return 1;
  if (!host_apply_seventh(1, 2, 3, 4, 5, 6, mini_to_big, CODE_NEG))
    return 2;
  return 0;
}
EOF
./minicc tmp-enum-abi-mini-callback-caller.c > tmp-enum-abi-mini-callback-caller.s
cc -o tmp-enum-abi-callback-mini-to-host tmp-enum-abi-mini-callback-caller.s tmp-enum-abi-host-callback-callee.o
./tmp-enum-abi-callback-mini-to-host

echo 'OK(enum callback ABI): minicc callback -> host indirect call'

echo 'All enum ABI tests passed!'
