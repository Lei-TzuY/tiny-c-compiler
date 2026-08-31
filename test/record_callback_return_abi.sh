#!/bin/bash
set -eu

cat > tmp-record-callback-return-minicc.c <<'EOF'
struct Pair { long a; long b; };
struct FP { double x; double y; };
struct Mixed { double x; long y; };
struct Big { long a; long b; long c; };

struct Pair minicc_pair_cb(long a, long b) {
  struct Pair r = {a, b};
  return r;
}

struct FP minicc_fp_cb(double x, double y) {
  struct FP r = {x, y};
  return r;
}

struct Mixed minicc_mixed_cb(double x, long y) {
  struct Mixed r = {x, y};
  return r;
}

struct Big minicc_big_cb(long a, long b, long c) {
  struct Big r = {a, b, c};
  return r;
}

struct Pair minicc_apply_pair(struct Pair (*cb)(long, long), long a, long b) {
  return cb(a, b);
}

struct FP minicc_apply_fp(struct FP (*cb)(double, double), double x, double y) {
  return cb(x, y);
}

struct Mixed minicc_apply_mixed(struct Mixed (*cb)(double, long), double x, long y) {
  return cb(x, y);
}

struct Big minicc_apply_big(struct Big (*cb)(long, long, long), long a, long b, long c) {
  return cb(a, b, c);
}
EOF

cat > tmp-record-callback-return-host.c <<'EOF'
struct Pair { long a; long b; };
struct FP { double x; double y; };
struct Mixed { double x; long y; };
struct Big { long a; long b; long c; };

struct Pair minicc_pair_cb(long, long);
struct FP minicc_fp_cb(double, double);
struct Mixed minicc_mixed_cb(double, long);
struct Big minicc_big_cb(long, long, long);

struct Pair minicc_apply_pair(struct Pair (*)(long, long), long, long);
struct FP minicc_apply_fp(struct FP (*)(double, double), double, double);
struct Mixed minicc_apply_mixed(struct Mixed (*)(double, long), double, long);
struct Big minicc_apply_big(struct Big (*)(long, long, long), long, long, long);

static struct Pair host_pair_cb(long a, long b) {
  struct Pair r = {a, b};
  return r;
}

static struct FP host_fp_cb(double x, double y) {
  struct FP r = {x, y};
  return r;
}

static struct Mixed host_mixed_cb(double x, long y) {
  struct Mixed r = {x, y};
  return r;
}

static struct Big host_big_cb(long a, long b, long c) {
  struct Big r = {a, b, c};
  return r;
}

static struct Pair host_apply_pair(struct Pair (*cb)(long, long), long a, long b) {
  return cb(a, b);
}

static struct FP host_apply_fp(struct FP (*cb)(double, double), double x, double y) {
  return cb(x, y);
}

static struct Mixed host_apply_mixed(struct Mixed (*cb)(double, long), double x, long y) {
  return cb(x, y);
}

static struct Big host_apply_big(struct Big (*cb)(long, long, long), long a, long b, long c) {
  return cb(a, b, c);
}

int main(void) {
  struct Pair pair = minicc_apply_pair(host_pair_cb, 40, 2);
  if (pair.a != 40 || pair.b != 2) return 1;

  struct FP fp = minicc_apply_fp(host_fp_cb, 20.25, 21.75);
  if (fp.x != 20.25 || fp.y != 21.75) return 2;

  struct Mixed mixed = minicc_apply_mixed(host_mixed_cb, 20.5, 22);
  if (mixed.x != 20.5 || mixed.y != 22) return 3;

  struct Big big = minicc_apply_big(host_big_cb, 10, 11, 21);
  if (big.a != 10 || big.b != 11 || big.c != 21) return 4;

  pair = host_apply_pair(minicc_pair_cb, 41, 1);
  if (pair.a != 41 || pair.b != 1) return 5;

  fp = host_apply_fp(minicc_fp_cb, 19.5, 22.5);
  if (fp.x != 19.5 || fp.y != 22.5) return 6;

  mixed = host_apply_mixed(minicc_mixed_cb, 19.25, 23);
  if (mixed.x != 19.25 || mixed.y != 23) return 7;

  big = host_apply_big(minicc_big_cb, 12, 13, 17);
  if (big.a != 12 || big.b != 13 || big.c != 17) return 8;

  return 0;
}
EOF

./minicc tmp-record-callback-return-minicc.c > tmp-record-callback-return-minicc.s
cc -c -o tmp-record-callback-return-minicc.o tmp-record-callback-return-minicc.s
cc -c -o tmp-record-callback-return-host.o tmp-record-callback-return-host.c
cc -o tmp-record-callback-return tmp-record-callback-return-host.o tmp-record-callback-return-minicc.o
./tmp-record-callback-return

echo "OK(record callback return ABI): INTEGER, SSE, mixed, and MEMORY-class aggregate returns"
rm -f tmp-record-callback-return-minicc.c tmp-record-callback-return-minicc.s \
      tmp-record-callback-return-minicc.o tmp-record-callback-return-host.c \
      tmp-record-callback-return-host.o tmp-record-callback-return