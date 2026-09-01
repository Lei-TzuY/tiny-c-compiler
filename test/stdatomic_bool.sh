#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cat >"$TMP/atomic_bool.c" <<'EOF'
#include <stdatomic.h>

static atomic_bool flag = ATOMIC_VAR_INIT(0);
static int pointer_calls;

static atomic_bool *get_flag(void) {
  pointer_calls++;
  return &flag;
}

int main(void) {
  _Static_assert(sizeof(atomic_bool) == sizeof(_Bool), "atomic bool representation");
  _Static_assert(ATOMIC_BOOL_LOCK_FREE == 2, "bool lock-free");

  atomic_store(&flag, 42);
  if (atomic_load(&flag) != 1) return 1;

  if (atomic_exchange(&flag, 0) != 1) return 2;
  if (atomic_load_explicit(&flag, memory_order_relaxed) != 0) return 3;

  atomic_store_explicit(&flag, -7, memory_order_release);
  if (atomic_load_explicit(&flag, memory_order_acquire) != 1) return 4;

  _Bool expected = 1;
  if (!atomic_compare_exchange_strong(&flag, &expected, 0)) return 5;
  if (expected != 1 || atomic_load(&flag) != 0) return 6;

  expected = 1;
  if (atomic_compare_exchange_weak(&flag, &expected, 1)) return 7;
  if (expected != 0 || atomic_load(&flag) != 0) return 8;

  expected = 0;
  if (!atomic_compare_exchange_strong(&flag, &expected, 99)) return 9;
  if (atomic_load(&flag) != 1) return 10;

  pointer_calls = 0;
  atomic_store(get_flag(), 0);
  if (pointer_calls != 1 || atomic_load(&flag) != 0) return 11;

  volatile atomic_bool volatile_flag = ATOMIC_VAR_INIT(0);
  atomic_store_explicit(&volatile_flag, 5, memory_order_relaxed);
  if (atomic_load_explicit(&volatile_flag, memory_order_relaxed) != 1) return 12;

  return 0;
}
EOF

./minicc --link "$TMP/atomic_bool.c" -o "$TMP/atomic_bool"
"$TMP/atomic_bool"

./minicc -S "$TMP/atomic_bool.c" -o "$TMP/atomic_bool.s"
grep -q 'xchgb' "$TMP/atomic_bool.s"
grep -q 'lock cmpxchgb' "$TMP/atomic_bool.s"

echo 'stdatomic bool semantics: ok'

cat >"$TMP/bad_expected.c" <<'EOF'
#include <stdatomic.h>
atomic_bool flag;
char expected;
int main(void) {
  return atomic_compare_exchange_strong(&flag, &expected, 1);
}
EOF
if ./minicc -fsyntax-only "$TMP/bad_expected.c" >"$TMP/bad_expected.out" 2>"$TMP/bad_expected.err"; then
  echo 'expected incompatible atomic_bool compare-exchange expected type to fail' >&2
  exit 1
fi
grep -F 'atomic compare-exchange expected argument has incompatible pointer type' "$TMP/bad_expected.err" >/dev/null

echo 'stdatomic bool constraints: ok'
