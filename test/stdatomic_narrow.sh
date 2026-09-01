#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cat >"$TMP/narrow.c" <<'EOF'
#include <stdatomic.h>

atomic_schar sc = -120;
atomic_uchar uc = 250;
atomic_short ss = -30000;
atomic_ushort us = 65000;

int main(void) {
  _Static_assert(sizeof(atomic_schar) == 1, "atomic signed char width");
  _Static_assert(sizeof(atomic_uchar) == 1, "atomic unsigned char width");
  _Static_assert(sizeof(atomic_short) == 2, "atomic short width");
  _Static_assert(sizeof(atomic_ushort) == 2, "atomic unsigned short width");

  if (atomic_load(&sc) != -120) return 1;
  if (atomic_load(&uc) != 250) return 2;
  if (atomic_load(&ss) != -30000) return 3;
  if (atomic_load(&us) != 65000) return 4;

  if (atomic_exchange(&sc, 120) != -120 || atomic_load(&sc) != 120) return 5;
  if (atomic_fetch_add(&uc, 10) != 250 || atomic_load(&uc) != 4) return 6;
  if (atomic_fetch_sub(&us, 1000) != 65000 || atomic_load(&us) != 64000) return 7;
  if (atomic_fetch_xor(&ss, 0x55) != -30000 || atomic_load(&ss) != (-30000 ^ 0x55)) return 8;

  signed char expected_sc = -1;
  if (atomic_compare_exchange_strong(&sc, &expected_sc, -7)) return 9;
  if (expected_sc != 120 || atomic_load(&sc) != 120) return 10;
  if (!atomic_compare_exchange_strong(&sc, &expected_sc, -7)) return 11;
  if (expected_sc != 120 || atomic_load(&sc) != -7) return 12;

  unsigned short expected_us = 123;
  if (atomic_compare_exchange_weak(&us, &expected_us, 7)) return 13;
  if (expected_us != 64000 || atomic_load(&us) != 64000) return 14;
  if (!atomic_compare_exchange_weak(&us, &expected_us, 7)) return 15;
  if (atomic_load(&us) != 7) return 16;

  _Atomic signed char op8 = 10;
  _Atomic unsigned short op16 = 1000;
  op8 += 5;
  op8 *= 2;
  op16 -= 250;
  op16 |= 0x100;
  if (op8 != 30) return 17;
  if (op16 != (750 | 0x100)) return 18;

  return 0;
}
EOF

./minicc --link "$TMP/narrow.c" -o "$TMP/narrow"
"$TMP/narrow"

# Lock down the byte/word instruction forms used by the narrow atomic backend.
./minicc -S "$TMP/narrow.c" -o "$TMP/narrow.s"
grep -Eq 'xchgb ' "$TMP/narrow.s"
grep -Eq 'lock xaddb ' "$TMP/narrow.s"
grep -Eq 'lock xaddw ' "$TMP/narrow.s"
grep -Eq 'lock cmpxchgb ' "$TMP/narrow.s"
grep -Eq 'lock cmpxchgw ' "$TMP/narrow.s"

echo 'stdatomic narrow-width operations: ok'
