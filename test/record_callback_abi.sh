#!/bin/bash
set -eu

cat > tmp-record-callback-minicc.c <<'EOF'
struct Pair { long a; long b; };
struct FP { double x; double y; };
struct Mixed { double x; long y; };
struct Big { long a; long b; long c; };

long minicc_pair_cb(struct Pair p) { return p.a * 10 + p.b; }
double minicc_fp_cb(struct FP p) { return p.x + p.y; }
double minicc_mixed_cb(struct Mixed p) { return p.x + p.y; }
long minicc_big_cb(struct Big p) { return p.a + p.b + p.c; }

long minicc_apply_pair(long (*cb)(struct Pair), struct Pair p) { return cb(p); }
double minicc_apply_fp(double (*cb)(struct FP), struct FP p) { return cb(p); }
double minicc_apply_mixed(double (*cb)(struct Mixed), struct Mixed p) { return cb(p); }
long minicc_apply_big(long (*cb)(struct Big), struct Big p) { return cb(p); }
EOF

cat > tmp-record-callback-host.c <<'EOF'
struct Pair { long a; long b; };
struct FP { double x; double y; };
struct Mixed { double x; long y; };
struct Big { long a; long b; long c; };

long minicc_pair_cb(struct Pair);
double minicc_fp_cb(struct FP);
double minicc_mixed_cb(struct Mixed);
long minicc_big_cb(struct Big);

long minicc_apply_pair(long (*)(struct Pair), struct Pair);
double minicc_apply_fp(double (*)(struct FP), struct FP);
double minicc_apply_mixed(double (*)(struct Mixed), struct Mixed);
long minicc_apply_big(long (*)(struct Big), struct Big);

static long host_pair_cb(struct Pair p) { return p.a * 10 + p.b; }
static double host_fp_cb(struct FP p) { return p.x + p.y; }
static double host_mixed_cb(struct Mixed p) { return p.x + p.y; }
static long host_big_cb(struct Big p) { return p.a + p.b + p.c; }

static long host_apply_pair(long (*cb)(struct Pair), struct Pair p) { return cb(p); }
static double host_apply_fp(double (*cb)(struct FP), struct FP p) { return cb(p); }
static double host_apply_mixed(double (*cb)(struct Mixed), struct Mixed p) { return cb(p); }
static long host_apply_big(long (*cb)(struct Big), struct Big p) { return cb(p); }

int main(void) {
  struct Pair pair = {4, 2};
  struct FP fp = {20.25, 21.75};
  struct Mixed mixed = {20.5, 22};
  struct Big big = {10, 11, 21};

  /* host callback -> minicc indirect call */
  if (minicc_apply_pair(host_pair_cb, pair) != 42) return 1;
  if (minicc_apply_fp(host_fp_cb, fp) != 42.0) return 2;
  if (minicc_apply_mixed(host_mixed_cb, mixed) != 42.5) return 3;
  if (minicc_apply_big(host_big_cb, big) != 42) return 4;

  /* minicc callback -> host indirect call */
  if (host_apply_pair(minicc_pair_cb, pair) != 42) return 5;
  if (host_apply_fp(minicc_fp_cb, fp) != 42.0) return 6;
  if (host_apply_mixed(minicc_mixed_cb, mixed) != 42.5) return 7;
  if (host_apply_big(minicc_big_cb, big) != 42) return 8;

  return 0;
}
EOF

./minicc tmp-record-callback-minicc.c > tmp-record-callback-minicc.s
cc -c -o tmp-record-callback-minicc.o tmp-record-callback-minicc.s
cc -c -o tmp-record-callback-host.o tmp-record-callback-host.c
cc -o tmp-record-callback tmp-record-callback-host.o tmp-record-callback-minicc.o
./tmp-record-callback

echo "OK(record callback ABI): INTEGER, SSE, mixed, and MEMORY-class aggregate arguments"
rm -f tmp-record-callback-minicc.c tmp-record-callback-minicc.s tmp-record-callback-minicc.o \
      tmp-record-callback-host.c tmp-record-callback-host.o tmp-record-callback
