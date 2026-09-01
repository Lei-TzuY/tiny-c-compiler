#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CC_BIN="$ROOT/minicc"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/contention.c" <<'EOF'
#include <stdatomic.h>

typedef unsigned long pthread_t;
int pthread_create(pthread_t *restrict thread, const void *restrict attr,
                   void *(*start_routine)(void *), void *restrict arg);
int pthread_join(pthread_t thread, void **retval);

enum { THREADS = 4, ITERS = 20000 };

static _Atomic float af = 0.0f;
static _Atomic double ad = 0.0;
static atomic_int ready = 0;
static atomic_int go = 0;

static void *worker(void *arg) {
  (void)arg;
  atomic_fetch_add(&ready, 1);
  while (!atomic_load(&go))
    ;

  for (int i = 0; i < ITERS; i++) {
    af += 1.0f;
    ad += 1.0;
  }
  return (void *)0;
}

int main(void) {
  pthread_t threads[THREADS];
  for (int i = 0; i < THREADS; i++)
    if (pthread_create(&threads[i], (void *)0, worker, (void *)0))
      return 1;

  while (atomic_load(&ready) != THREADS)
    ;
  atomic_store(&go, 1);

  for (int i = 0; i < THREADS; i++)
    if (pthread_join(threads[i], (void **)0))
      return 2;

  float f = atomic_load(&af);
  double d = atomic_load(&ad);
  if (f != (float)(THREADS * ITERS))
    return 3;
  if (d != (double)(THREADS * ITERS))
    return 4;
  return 0;
}
EOF

"$CC_BIN" "$TMP/contention.c" > "$TMP/contention.s"
gcc -pthread -o "$TMP/contention" "$TMP/contention.s"
"$TMP/contention"

grep -q 'addss' "$TMP/contention.s"
grep -q 'addsd' "$TMP/contention.s"
grep -q 'lock cmpxchgl' "$TMP/contention.s"
grep -q 'lock cmpxchgq' "$TMP/contention.s"

echo "stdatomic floating contention tests passed"
