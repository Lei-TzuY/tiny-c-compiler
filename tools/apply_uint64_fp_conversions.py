from pathlib import Path

p = Path('codegen.c')
s = p.read_text()
old = r'''    if (is_integer(from) && is_flonum(to)) {
        if (to->kind == TY_FLOAT)
            printf("  cvtsi2ss %%rax, %%xmm0\n");
        else
            printf("  cvtsi2sd %%rax, %%xmm0\n");
        return;
    }

    if (is_flonum(from) && is_integer(to)) {
        if (from->kind == TY_FLOAT)
            printf("  cvttss2si %%xmm0, %%rax\n");
        else
            printf("  cvttsd2si %%xmm0, %%rax\n");
        normalize(to);
        return;
    }
'''
new = r'''    if (is_integer(from) && is_flonum(to)) {
        // SSE2 only provides signed 64-bit integer-to-float conversion.  For
        // unsigned long values with the high bit set, halve the value while
        // preserving the dropped low bit, convert the now-signed-positive
        // integer, then double the floating result.  This is the standard
        // exact-rounding reduction used for the full uint64_t domain.
        if (from->kind == TY_LONG && from->is_unsigned) {
            int c = count();
            printf("  test %%rax, %%rax\n");
            printf("  js .L.u64_to_fp.%d\n", c);
            if (to->kind == TY_FLOAT)
                printf("  cvtsi2ss %%rax, %%xmm0\n");
            else
                printf("  cvtsi2sd %%rax, %%xmm0\n");
            printf("  jmp .L.u64_to_fp_end.%d\n", c);
            printf(".L.u64_to_fp.%d:\n", c);
            printf("  mov %%rax, %%rdx\n");
            printf("  and $1, %%eax\n");
            printf("  shr $1, %%rdx\n");
            printf("  or %%rax, %%rdx\n");
            if (to->kind == TY_FLOAT) {
                printf("  cvtsi2ss %%rdx, %%xmm0\n");
                printf("  addss %%xmm0, %%xmm0\n");
            } else {
                printf("  cvtsi2sd %%rdx, %%xmm0\n");
                printf("  addsd %%xmm0, %%xmm0\n");
            }
            printf(".L.u64_to_fp_end.%d:\n", c);
            return;
        }

        if (to->kind == TY_FLOAT)
            printf("  cvtsi2ss %%rax, %%xmm0\n");
        else
            printf("  cvtsi2sd %%rax, %%xmm0\n");
        return;
    }

    if (is_flonum(from) && is_integer(to)) {
        // cvtt{s,d}2si also targets signed 64-bit integers.  Values in the
        // upper half of uint64_t are converted after subtracting 2^63, then
        // the high bit is restored in the integer result.  C leaves negative,
        // NaN, and out-of-range floating conversions undefined, so only the
        // representable unsigned range needs a defined lowering here.
        if (to->kind == TY_LONG && to->is_unsigned) {
            int c = count();
            if (from->kind == TY_FLOAT) {
                printf("  mov $0x5f000000, %%edx\n");
                printf("  movd %%edx, %%xmm1\n");
                printf("  ucomiss %%xmm1, %%xmm0\n");
                printf("  jb .L.fp_to_u64_low.%d\n", c);
                printf("  subss %%xmm1, %%xmm0\n");
                printf("  cvttss2si %%xmm0, %%rax\n");
            } else {
                printf("  movabs $0x43e0000000000000, %%rdx\n");
                printf("  movq %%rdx, %%xmm1\n");
                printf("  ucomisd %%xmm1, %%xmm0\n");
                printf("  jb .L.fp_to_u64_low.%d\n", c);
                printf("  subsd %%xmm1, %%xmm0\n");
                printf("  cvttsd2si %%xmm0, %%rax\n");
            }
            printf("  movabs $0x8000000000000000, %%rdx\n");
            printf("  or %%rdx, %%rax\n");
            printf("  jmp .L.fp_to_u64_end.%d\n", c);
            printf(".L.fp_to_u64_low.%d:\n", c);
            if (from->kind == TY_FLOAT)
                printf("  cvttss2si %%xmm0, %%rax\n");
            else
                printf("  cvttsd2si %%xmm0, %%rax\n");
            printf(".L.fp_to_u64_end.%d:\n", c);
            return;
        }

        if (from->kind == TY_FLOAT)
            printf("  cvttss2si %%xmm0, %%rax\n");
        else
            printf("  cvttsd2si %%xmm0, %%rax\n");
        normalize(to);
        return;
    }
'''
if s.count(old) != 1:
    raise SystemExit(f'cast block anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))

p = Path('test/uint64_fp_conversions.sh')
p.write_text(r'''#!/bin/bash
set -eu

assert_run() {
  input="$1"
  printf '%s\n' "$input" > tmp-u64fp.c
  ./minicc tmp-u64fp.c > tmp-u64fp.s
  cc -o tmp-u64fp tmp-u64fp.s
  set +e
  ./tmp-u64fp
  actual="$?"
  set -e
  if [ "$actual" != 0 ]; then
    echo "uint64/floating conversion test failed with exit $actual"
    echo "$input"
    exit 1
  fi
}

# unsigned long -> double: high-half values must not be interpreted as signed.
assert_run 'int main(){unsigned long x=(unsigned long)1<<63;double d=(double)x;return d==9223372036854775808.0?0:1;}'
assert_run 'int main(){unsigned long x=((unsigned long)1<<63)+2048;double d=(double)x;return d==9223372036854777856.0?0:1;}'
assert_run 'int main(){unsigned long x=~(unsigned long)0;double d=(double)x;return d==18446744073709551616.0?0:1;}'

# unsigned long -> float, including one ULP above 2^63.
assert_run 'int main(){unsigned long x=(unsigned long)1<<63;float f=(float)x;return f==9223372036854775808.0f?0:1;}'
assert_run 'int main(){unsigned long x=((unsigned long)1<<63)+((unsigned long)1<<40);float f=(float)x;return f==9223373136366403584.0f?0:1;}'

# double -> unsigned long across the signed boundary and near UINT64_MAX.
assert_run 'int main(){double d=9223372036854775808.0;unsigned long x=(unsigned long)d;return x==((unsigned long)1<<63)?0:1;}'
assert_run 'int main(){double d=9223372036854777856.0;unsigned long x=(unsigned long)d;return x==(((unsigned long)1<<63)+2048)?0:1;}'
assert_run 'int main(){double d=18446744073709549568.0;unsigned long x=(unsigned long)d;return x==(~(unsigned long)0-2047)?0:1;}'

# float -> unsigned long across the same boundary.
assert_run 'int main(){float f=9223372036854775808.0f;unsigned long x=(unsigned long)f;return x==((unsigned long)1<<63)?0:1;}'
assert_run 'int main(){float f=9223373136366403584.0f;unsigned long x=(unsigned long)f;return x==(((unsigned long)1<<63)+((unsigned long)1<<40))?0:1;}'
assert_run 'int main(){float f=18446742974197923840.0f;unsigned long x=(unsigned long)f;return x==(~(unsigned long)0-(((unsigned long)1<<40)-1))?0:1;}'

# Exercise implicit return conversions in both directions, not only explicit casts.
assert_run 'double f(unsigned long x){return x;}int main(){unsigned long x=((unsigned long)1<<63)+2048;return f(x)==9223372036854777856.0?0:1;}'
assert_run 'unsigned long f(double x){return x;}int main(){return f(18446744073709549568.0)==(~(unsigned long)0-2047)?0:1;}'

echo 'All uint64/floating conversion tests passed!'
''')

p = Path('Makefile')
s = p.read_text()
old = '\tbash ./test/gnu_stack.sh\n'
new = old + '\tbash ./test/uint64_fp_conversions.sh\n'
if s.count(old) != 1:
    raise SystemExit(f'Makefile anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))

p = Path('README.md')
s = p.read_text()
old = 'The built-in educational `va_list` implementation remains integer-only.'
new = ('Full-range `unsigned long` conversions to and from `float`/`double` are lowered '
       'without signed-64 truncation. ' + old)
if s.count(old) != 1:
    raise SystemExit(f'README anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))
