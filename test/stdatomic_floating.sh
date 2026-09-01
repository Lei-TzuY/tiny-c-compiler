#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CC_BIN="$ROOT/minicc"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/main.c" <<'EOF'
#include <stdatomic.h>

_Atomic float gf = 1.25f;
_Atomic(double) gd = 2.5;

union FU { float f; unsigned int u; };
union DU { double d; unsigned long u; };

static int closef(float a, float b) {
  float d = a - b;
  return d > -0.0001f && d < 0.0001f;
}

static int closed(double a, double b) {
  double d = a - b;
  return d > -0.0000001 && d < 0.0000001;
}

int main(void) {
  _Static_assert(sizeof(_Atomic float) == 4, "atomic float size");
  _Static_assert(sizeof(_Atomic(double)) == 8, "atomic double size");
  _Static_assert(_Alignof(_Atomic float) == 4, "atomic float align");
  _Static_assert(_Alignof(_Atomic(double)) == 8, "atomic double align");

  if (!atomic_is_lock_free(&gf) || !atomic_is_lock_free(&gd)) return 1;
  if (!closef(gf, 1.25f) || !closed(gd, 2.5)) return 2;

  // Ordinary atomic assignment/load use seq-cst semantics and preserve the
  // assignment value in the floating register path.
  float fr = (gf = 3.5f);
  double dr = (gd = 7.25);
  if (!closef(fr, 3.5f) || !closed(dr, 7.25)) return 3;
  if (!closef(gf, 3.5f) || !closed(gd, 7.25)) return 4;

  atomic_store_explicit(&gf, 4.5f, memory_order_relaxed);
  atomic_store_explicit(&gd, 8.5, memory_order_release);
  if (!closef(atomic_load_explicit(&gf, memory_order_acquire), 4.5f)) return 5;
  if (!closed(atomic_load(&gd), 8.5)) return 6;

  if (!closef(atomic_exchange(&gf, 6.0f), 4.5f) || !closef(gf, 6.0f)) return 7;
  if (!closed(atomic_exchange_explicit(&gd, 10.0, memory_order_acq_rel), 8.5) ||
      !closed(gd, 10.0)) return 8;

  float ef = 6.0f;
  if (!atomic_compare_exchange_strong(&gf, &ef, 7.0f)) return 9;
  if (!closef(gf, 7.0f)) return 10;
  ef = 123.0f;
  if (atomic_compare_exchange_weak_explicit(&gf, &ef, 9.0f, memory_order_acq_rel, memory_order_relaxed)) return 11;
  if (!closef(ef, 7.0f) || !closef(gf, 7.0f)) return 12;

  double ed = 10.0;
  if (!atomic_compare_exchange_strong(&gd, &ed, 11.5)) return 13;
  if (!closed(gd, 11.5)) return 14;

  // Floating compound assignment and inc/dec are atomic RMW operations. The
  // returned value follows normal C prefix/postfix semantics.
  fr = (gf += 0.5f);
  if (!closef(fr, 7.5f) || !closef(gf, 7.5f)) return 15;
  fr = (gf *= 2.0f);
  if (!closef(fr, 15.0f) || !closef(gf, 15.0f)) return 16;
  fr = (gf /= 3.0f);
  if (!closef(fr, 5.0f) || !closef(gf, 5.0f)) return 17;
  fr = gf++;
  if (!closef(fr, 5.0f) || !closef(gf, 6.0f)) return 18;
  fr = --gf;
  if (!closef(fr, 5.0f) || !closef(gf, 5.0f)) return 19;

  dr = (gd -= 1.5);
  if (!closed(dr, 10.0) || !closed(gd, 10.0)) return 20;
  dr = gd--;
  if (!closed(dr, 10.0) || !closed(gd, 9.0)) return 21;
  dr = ++gd;
  if (!closed(dr, 10.0) || !closed(gd, 10.0)) return 22;

  // Compare-exchange is representation-based (matching the corrected C atomic
  // semantics and x86 cmpxchg). +0 and -0 compare differently at the bit level.
  atomic_store(&gf, -0.0f);
  ef = 0.0f;
  if (atomic_compare_exchange_strong(&gf, &ef, 1.0f)) return 23;
  union FU ez = { .f = ef };
  if (ez.u != 0x80000000u) return 24;

  // Identical NaN payloads can match without a floating equality operation.
  union FU nanbits = { .u = 0x7fc01234u };
  atomic_store(&gf, nanbits.f);
  ef = nanbits.f;
  if (!atomic_compare_exchange_strong(&gf, &ef, 2.0f)) return 25;
  if (!closef(gf, 2.0f)) return 26;

  union DU dn = { .u = 0x7ff8000000001234ul };
  atomic_store(&gd, dn.d);
  ed = dn.d;
  if (!atomic_compare_exchange_strong(&gd, &ed, 3.0)) return 27;
  if (!closed(gd, 3.0)) return 28;

  return 0;
}
EOF

"$CC_BIN" "$TMP/main.c" > "$TMP/main.s"
gcc -o "$TMP/main" "$TMP/main.s"
"$TMP/main"

grep -q 'xchgl' "$TMP/main.s"
grep -q 'xchgq' "$TMP/main.s"
grep -q 'lock cmpxchgl' "$TMP/main.s"
grep -q 'lock cmpxchgq' "$TMP/main.s"
grep -q 'addss' "$TMP/main.s"
grep -q 'muls' "$TMP/main.s"
grep -q 'subsd' "$TMP/main.s"

# C11 generic atomic_fetch_add/sub remain restricted to integer/pointer objects.
cat > "$TMP/bad_fetch.c" <<'EOF'
#include <stdatomic.h>
int main(void) {
  _Atomic float x = 1.0f;
  (void)atomic_fetch_add(&x, 1.0f);
  return 0;
}
EOF
if "$CC_BIN" -fsyntax-only "$TMP/bad_fetch.c" >"$TMP/out" 2>"$TMP/err"; then
  echo "expected atomic_fetch_add on floating atomic to fail" >&2
  exit 1
fi
grep -q 'atomic fetch-add/sub requires integer or pointer type' "$TMP/err"

# Cross-compiler object-layout interoperability: GCC defines the atomic objects,
# minicc performs floating atomic operations, then GCC verifies the result.
cat > "$TMP/host.c" <<'EOF'
#include <stdatomic.h>
_Atomic float host_af = 1.5f;
_Atomic double host_ad = 2.25;
extern int minicc_touch(void);
int main(void) {
  if (minicc_touch() != 0) return 1;
  float f = atomic_load(&host_af);
  double d = atomic_load(&host_ad);
  if (!(f > 4.49f && f < 4.51f)) return 2;
  if (!(d > 7.49 && d < 7.51)) return 3;
  return 0;
}
EOF
cat > "$TMP/minicc_part.c" <<'EOF'
#include <stdatomic.h>
extern _Atomic float host_af;
extern _Atomic double host_ad;
int minicc_touch(void) {
  if (atomic_exchange(&host_af, 3.5f) != 1.5f) return 1;
  host_af += 1.0f;
  if (atomic_exchange(&host_ad, 6.5) != 2.25) return 2;
  ++host_ad;
  return 0;
}
EOF
"$CC_BIN" -c "$TMP/minicc_part.c" -o "$TMP/minicc_part.o"
gcc -std=c11 -c "$TMP/host.c" -o "$TMP/host.o"
gcc -o "$TMP/cross" "$TMP/host.o" "$TMP/minicc_part.o"
"$TMP/cross"

echo "stdatomic floating tests passed"
