#!/bin/bash
set -eu

# Function pointers are INTEGER-class variadic arguments under the SysV AMD64
# ABI. Exercise both register and overflow-stack paths in both compiler
# directions so minicc cannot accidentally agree with itself on a bad layout.

cat > tmp-vfp-host-callee.c <<'EOF'
#include <stdarg.h>

int host_apply_var(int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int (*fn)(int) = va_arg(ap, int (*)(int));
  int x = va_arg(ap, int);
  va_end(ap);
  return fn(x);
}

int host_apply_var_stack(int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int sum = 0;
  for (int i = 0; i < 5; i++)
    sum += va_arg(ap, int);
  int (*fn)(int) = va_arg(ap, int (*)(int));
  int x = va_arg(ap, int);
  va_end(ap);
  return sum + fn(x);
}
EOF
cc -c -o tmp-vfp-host-callee.o tmp-vfp-host-callee.c

cat > tmp-vfp-minicc-caller.c <<'EOF'
int host_apply_var(int, ...);
int host_apply_var_stack(int, ...);

static int plus3(int x) { return x + 3; }

int main(void) {
  if (host_apply_var(0, plus3, 39) != 42)
    return 1;
  if (host_apply_var_stack(0, 1, 2, 3, 4, 5, plus3, 24) != 42)
    return 2;
  return 0;
}
EOF
./minicc tmp-vfp-minicc-caller.c > tmp-vfp-minicc-caller.s
cc -o tmp-vfp-minicc-caller tmp-vfp-minicc-caller.s tmp-vfp-host-callee.o
./tmp-vfp-minicc-caller
echo "OK(variadic function pointer ABI): minicc caller -> host callee"

cat > tmp-vfp-minicc-callee.c <<'EOF'
#include <stdarg.h>

int minicc_apply_var(int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int (*fn)(int) = va_arg(ap, int (*)(int));
  int x = va_arg(ap, int);
  va_end(ap);
  return fn(x);
}

int minicc_apply_var_stack(int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int sum = 0;
  for (int i = 0; i < 5; i++)
    sum += va_arg(ap, int);
  int (*fn)(int) = va_arg(ap, int (*)(int));
  int x = va_arg(ap, int);
  va_end(ap);
  return sum + fn(x);
}
EOF
./minicc tmp-vfp-minicc-callee.c > tmp-vfp-minicc-callee.s
cc -c -o tmp-vfp-minicc-callee.o tmp-vfp-minicc-callee.s

cat > tmp-vfp-host-caller.c <<'EOF'
int minicc_apply_var(int, ...);
int minicc_apply_var_stack(int, ...);

static int times2(int x) { return x * 2; }

int main(void) {
  if (minicc_apply_var(0, times2, 21) != 42)
    return 1;
  if (minicc_apply_var_stack(0, 1, 2, 3, 4, 5, times2, 13) != 41)
    return 2;
  return 0;
}
EOF
cc -o tmp-vfp-host-caller tmp-vfp-host-caller.c tmp-vfp-minicc-callee.o
./tmp-vfp-host-caller
echo "OK(variadic function pointer ABI): host caller -> minicc callee"

rm -f tmp-vfp-host-callee.c tmp-vfp-host-callee.o \
  tmp-vfp-minicc-caller.c tmp-vfp-minicc-caller.s tmp-vfp-minicc-caller \
  tmp-vfp-minicc-callee.c tmp-vfp-minicc-callee.s tmp-vfp-minicc-callee.o \
  tmp-vfp-host-caller.c tmp-vfp-host-caller

echo 'All variadic function-pointer ABI tests passed!'
