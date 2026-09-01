#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cat >"$TMP/pointer.c" <<'EOF'
#include <stdatomic.h>

struct Item {
  long key;
  int value;
  char tag[5];
};

static struct Item items[12];
static struct Item * _Atomic cursor = items + 2;
static int object_calls;
static int delta_calls;

static struct Item * _Atomic *cursor_addr(void) {
  object_calls++;
  return &cursor;
}

static int one(void) {
  delta_calls++;
  return 1;
}

int main(void) {
  _Static_assert(sizeof(cursor) == sizeof(struct Item *), "atomic pointer representation");
  _Static_assert(ATOMIC_POINTER_LOCK_FREE == 2, "pointer atomics are lock-free");

  if (atomic_load(&cursor) != items + 2) return 1;

  if (cursor++ != items + 2 || cursor != items + 3) return 2;
  if (++cursor != items + 4) return 3;
  if (cursor-- != items + 4 || cursor != items + 3) return 4;
  if (--cursor != items + 2) return 5;

  cursor += 2;
  if (cursor != items + 4) return 6;
  cursor -= 1;
  if (cursor != items + 3) return 7;

  if (atomic_fetch_add(&cursor, 3) != items + 3) return 8;
  if (atomic_load_explicit(&cursor, memory_order_relaxed) != items + 6) return 9;
  if (atomic_fetch_sub_explicit(&cursor, 2, memory_order_relaxed) != items + 6) return 10;
  if (cursor != items + 4) return 11;

  if (atomic_exchange(&cursor, items + 8) != items + 4) return 12;
  if (cursor != items + 8) return 13;

  struct Item *expected = items + 8;
  if (!atomic_compare_exchange_strong(&cursor, &expected, items + 1)) return 14;
  if (cursor != items + 1 || expected != items + 8) return 15;

  expected = items + 7;
  if (atomic_compare_exchange_weak_explicit(&cursor, &expected, items + 5, memory_order_acq_rel, memory_order_acquire)) return 16;
  if (cursor != items + 1 || expected != items + 1) return 17;

  object_calls = 0;
  if (atomic_fetch_add(cursor_addr(), 1) != items + 1) return 18;
  if (object_calls != 1 || cursor != items + 2) return 19;

  delta_calls = 0;
  if (atomic_fetch_sub(&cursor, one()) != items + 2) return 20;
  if (delta_calls != 1 || cursor != items + 1) return 21;

  return 0;
}
EOF

./minicc --link "$TMP/pointer.c" -o "$TMP/pointer"
"$TMP/pointer"

echo 'stdatomic pointer operations: ok'

# Pointer RMW must use pointer-width atomic instructions; runtime checks above
# independently prove that deltas scale by sizeof(*pointer), including a
# non-trivial struct element size.
./minicc -S "$TMP/pointer.c" -o "$TMP/pointer.s"
grep -q 'lock xaddq ' "$TMP/pointer.s"
grep -q 'lock cmpxchgq ' "$TMP/pointer.s"
grep -q 'xchgq ' "$TMP/pointer.s"

echo 'stdatomic pointer lowering: ok'

expect_fail() {
  local name=$1
  local needle=$2
  local text=$3
  printf '%b\n' "$text" >"$TMP/$name.c"
  if ./minicc -fsyntax-only "$TMP/$name.c" >"$TMP/$name.out" 2>"$TMP/$name.err"; then
    echo "expected failure: $name" >&2
    exit 1
  fi
  grep -F "$needle" "$TMP/$name.err" >/dev/null
}

expect_fail pointer_fetch_noninteger 'atomic pointer fetch-add/sub requires integer delta' '#include <stdatomic.h>\nint data[2]; int * _Atomic p=data; int main(void){ return atomic_fetch_add(&p, 1.5) != data; }'
expect_fail pointer_fetch_bitwise 'atomic bitwise fetch operation requires integer type' '#include <stdatomic.h>\nint data[2]; int * _Atomic p=data; int main(void){ return atomic_fetch_xor(&p, 1) != data; }'
expect_fail pointer_cas_expected 'atomic compare-exchange expected argument has incompatible pointer type' '#include <stdatomic.h>\nint data[2]; int * _Atomic p=data; long *expected=0; int main(void){ return atomic_compare_exchange_strong(&p, &expected, data+1); }'

echo 'stdatomic pointer constraints: ok'
