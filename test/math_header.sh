#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
MINICC="$ROOT/minicc"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

expect_fail() {
    if "$@" >fail.out 2>fail.err; then
        echo "expected failure: $*" >&2
        exit 1
    fi
}

cat > syntax.c <<'EOF'
#include <math.h>
float_t f;
double_t d;
int main(void) {
    int e = 0, q = 0;
    double ip = 0.0;
    f = sqrtf(4.0f) + sinf(0.0f) + cosf(0.0f);
    d = sqrt(9.0) + pow(2.0, 3.0) + hypot(3.0, 4.0);
    d += frexp(8.0, &e) + modf(3.25, &ip) + remquo(7.0, 2.0, &q);
    return fpclassify(f) + isfinite(d) + isnan(NAN) + isinf(INFINITY) + signbit(-1.0);
}
EOF
"$MINICC" -fsyntax-only syntax.c

printf '#include <math.h>\n' > pp.c
"$MINICC" -E pp.c > pp.out
grep -q 'double sqrt(double)' pp.out
grep -q '__minicc_fpclassify' pp.out

cat > probe.c <<'EOF'
#if !__has_include(<math.h>)
#error builtin math.h should be discoverable
#endif
int main(void) { return 0; }
EOF
"$MINICC" -fsyntax-only probe.c
expect_fail "$MINICC" -nostdinc -fsyntax-only pp.c

cat > runtime.c <<'EOF'
#include <math.h>
int main(void) {
    int e = 0, q = 0, side = 0;
    double ip = 0.0;
    double m = frexp(8.0, &e);
    double frac = modf(3.25, &ip);
    double rq = remquo(7.0, 2.0, &q);
    double n = nan("");
    if (sqrt(81.0) != 9.0 || pow(2.0, 5.0) != 32.0 || hypot(3.0, 4.0) != 5.0) return 1;
    if (sqrtf(49.0f) != 7.0f || floor(3.75) != 3.0 || ceil(3.25) != 4.0) return 2;
    if (fabs(-4.5) != 4.5 || fmod(7.0, 2.0) != 1.0 || m != 0.5 || e != 4) return 3;
    if (frac != 0.25 || ip != 3.0 || rq != -1.0) return 4;
    if (!isnan(n) || !isnan(NAN) || !isinf(INFINITY) || !isfinite(M_PI) || !isnormal(1.0)) return 5;
    if (fpclassify(0.0) != FP_ZERO || fpclassify(1.0f) != FP_NORMAL) return 6;
    if (!signbit(copysign(0.0, -1.0)) || signbit(0.0)) return 7;
    if (!isgreater(2.0, 1.0) || !isgreaterequal(2.0, 2.0) || !isless(1.0, 2.0)) return 8;
    if (!islessequal(2.0, 2.0) || !islessgreater(1.0, 2.0) || !isunordered(n, 1.0)) return 9;
    if (!isfinite((side++, 1.0)) || side != 1) return 10;
    if (lround(2.6) != 3 || llround(-2.6) != -3) return 11;
    return 0;
}
EOF
"$MINICC" --link runtime.c -lm -o runtime
./runtime

echo 'math.h tests passed'
