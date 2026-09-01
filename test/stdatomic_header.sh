#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

compile_run() {
  local src=$1
  ./minicc --link "$src" -o "$TMP/a.out"
  "$TMP/a.out"
}

cat >"$TMP/basic.c" <<'EOF'
#include <stdatomic.h>

_Atomic int raw = 3;
_Atomic(int) spec = 4;
atomic_int ai = ATOMIC_VAR_INIT(5);
atomic_uint au = 7;
atomic_flag flag = ATOMIC_FLAG_INIT;

int main(void) {
  _Static_assert(sizeof(atomic_int) == sizeof(int), "atomic int representation");
  _Static_assert(sizeof(atomic_long) == sizeof(long), "atomic long representation");
  _Static_assert(ATOMIC_INT_LOCK_FREE == 2, "int lock-free");
  _Static_assert(ATOMIC_POINTER_LOCK_FREE == 2, "pointer lock-free");

  if (raw != 3 || spec != 4 || atomic_load(&ai) != 5) return 1;
  atomic_store(&ai, 9);
  if (atomic_load_explicit(&ai, memory_order_relaxed) != 9) return 2;
  if (atomic_exchange(&ai, 12) != 9 || ai != 12) return 3;
  if (atomic_fetch_add(&ai, 5) != 12 || ai != 17) return 4;
  if (atomic_fetch_sub(&ai, 2) != 17 || ai != 15) return 5;
  if (atomic_fetch_or(&au, 8) != 7 || au != 15) return 6;
  if (atomic_fetch_and(&au, 12) != 15 || au != 12) return 7;
  if (atomic_fetch_xor(&au, 10) != 12 || au != 6) return 8;

  int expected = 15;
  if (!atomic_compare_exchange_strong(&ai, &expected, 33)) return 9;
  if (ai != 33 || expected != 15) return 10;
  expected = 11;
  if (atomic_compare_exchange_weak(&ai, &expected, 44)) return 11;
  if (expected != 33 || ai != 33) return 12;

  if (atomic_flag_test_and_set(&flag)) return 13;
  if (!atomic_flag_test_and_set_explicit(&flag, memory_order_acquire)) return 14;
  atomic_flag_clear_explicit(&flag, memory_order_release);
  if (atomic_flag_test_and_set(&flag)) return 15;

  int side = 0;
  (void)atomic_load_explicit(&ai, (side++, memory_order_relaxed));
  if (side != 1) return 16;
  if (!atomic_is_lock_free(&ai)) return 17;
  atomic_thread_fence(memory_order_seq_cst);
  atomic_signal_fence(memory_order_acq_rel);
  return 0;
}
EOF
compile_run "$TMP/basic.c"

echo 'stdatomic basic API: ok'

cat >"$TMP/operators.c" <<'EOF'
#include <stdatomic.h>
int data[8];
int main(void) {
  _Atomic int x = 2;
  if (x++ != 2 || x != 3) return 1;
  if (++x != 4) return 2;
  x += 7;
  x *= 3;
  x /= 2;
  x %= 9;
  x |= 16;
  x &= 23;
  x ^= 3;
  x <<= 1;
  x >>= 1;
  if (x != 20) return 3;

  int * _Atomic p = data;
  if (p != data) return 4;
  p += 3;
  if (p != data + 3) return 5;
  if (atomic_fetch_add(&p, 2) != data + 3) return 6;
  if (atomic_load(&p) != data + 5) return 7;

  _Atomic int *points_to_atomic = &x;
  if (atomic_load(points_to_atomic) != 20) return 8;
  return 0;
}
EOF
compile_run "$TMP/operators.c"

echo 'stdatomic operators/pointers: ok'

cat >"$TMP/threaded.c" <<'EOF'
#include <stdatomic.h>
typedef unsigned long pthread_t;
extern int pthread_create(pthread_t *, const void *, void *(*)(void *), void *);
extern int pthread_join(pthread_t, void **);

static atomic_int counter = ATOMIC_VAR_INIT(0);
static void *worker(void *unused) {
  (void)unused;
  for (int i = 0; i < 100000; i++)
    atomic_fetch_add_explicit(&counter, 1, memory_order_relaxed);
  return 0;
}

int main(void) {
  pthread_t a, b, c, d;
  if (pthread_create(&a, 0, worker, 0)) return 1;
  if (pthread_create(&b, 0, worker, 0)) return 2;
  if (pthread_create(&c, 0, worker, 0)) return 3;
  if (pthread_create(&d, 0, worker, 0)) return 4;
  pthread_join(a, 0); pthread_join(b, 0); pthread_join(c, 0); pthread_join(d, 0);
  return atomic_load(&counter) == 400000 ? 0 : 5;
}
EOF
./minicc -c "$TMP/threaded.c" -o "$TMP/threaded.o"
gcc -pthread "$TMP/threaded.o" -o "$TMP/threaded"
"$TMP/threaded"
echo 'stdatomic pthread contention: ok'

# Inspect lowering so a future accidental non-atomic load/modify/store rewrite is caught.
./minicc -S "$TMP/basic.c" -o "$TMP/basic.s"
grep -Eq 'xchg[bwlq]? ' "$TMP/basic.s"
grep -Eq 'lock xadd[bwlq]? ' "$TMP/basic.s"
grep -Eq 'lock cmpxchg[bwlq]? ' "$TMP/basic.s"
grep -q 'mfence' "$TMP/basic.s"
echo 'stdatomic lowering instructions: ok'

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

expect_fail atomic_float 'atomic backend supports only' '_Atomic float x; int main(void){return 0;}'
expect_fail atomic_record 'atomic backend supports only' 'struct S { int x; }; _Atomic(struct S) x; int main(void){return 0;}'
expect_fail atomic_array 'atomic backend supports only' '_Atomic(int[2]) x; int main(void){return 0;}'
expect_fail atomic_bitfield 'atomic bit-fields are not supported' 'struct S { _Atomic int x:3; }; int main(void){return 0;}'
expect_fail bad_load 'atomic operation requires a pointer to an atomic object' '#include <stdatomic.h>\nint x; int main(void){ return atomic_load(&x); }'
expect_fail bad_cas_expected 'atomic compare-exchange expected argument has incompatible pointer type' '#include <stdatomic.h>\natomic_int x; long expected; int main(void){ return atomic_compare_exchange_strong(&x, &expected, 1); }'

echo 'stdatomic constraints: ok'
