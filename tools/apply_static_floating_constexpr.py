from pathlib import Path

p = Path('parse.c')
s = p.read_text()

start = s.index('static double parse_const_double(Token **rest, Token *tok) {')
end = s.index('\nstatic void parse_static_scalar_initializer', start)

new = r'''typedef struct {
    Type *ty;
    bool is_fp;
    int64_t ival;
    double fval;
} ConstNumber;

static ConstNumber eval_const_number(Node *node);

static double const_number_as_double(ConstNumber v) {
    if (v.is_fp)
        return v.fval;

    if (!v.ty || !is_integer(v.ty))
        error("arithmetic constant expression required");

    int64_t val = cast_const_integer(v.ival, v.ty);
    if (v.ty->is_unsigned)
        return (double)(uint64_t)val;
    return (double)val;
}

static bool const_number_truth(ConstNumber v) {
    if (v.is_fp)
        return v.fval != 0.0;
    return cast_const_integer(v.ival, v.ty) != 0;
}

static ConstNumber const_number_cast(ConstNumber v, Type *ty) {
    if (!ty || (!is_integer(ty) && !is_flonum(ty)))
        error("arithmetic type required in constant expression cast");

    ConstNumber out = {.ty = ty};
    if (is_flonum(ty)) {
        double x = const_number_as_double(v);
        out.is_fp = true;
        out.fval = ty->kind == TY_FLOAT ? (double)(float)x : x;
        return out;
    }

    out.is_fp = false;
    if (ty->kind == TY_BOOL) {
        out.ival = const_number_truth(v);
        return out;
    }

    if (!v.is_fp) {
        out.ival = cast_const_integer(v.ival, ty);
        return out;
    }

    double x = v.fval;
    if (ty->is_unsigned) {
        if (!(x >= 0.0) || x >= 18446744073709551616.0)
            error("floating-to-unsigned conversion is out of range in constant expression");
        out.ival = cast_const_integer((int64_t)(uint64_t)x, ty);
        return out;
    }

    if (x < (double)INT64_MIN || x >= 9223372036854775808.0)
        error("floating-to-integer conversion is out of range in constant expression");
    out.ival = cast_const_integer((int64_t)x, ty);
    return out;
}

static ConstNumber eval_const_number(Node *node) {
    if (!node)
        error("expected arithmetic constant expression");

    add_type(node);

    if (is_integer(node->ty)) {
        switch (node->kind) {
        case ND_EQ:
        case ND_NE:
        case ND_LT:
        case ND_LE: {
            add_type(node->lhs);
            add_type(node->rhs);
            if (!is_flonum(node->lhs->ty) && !is_flonum(node->rhs->ty))
                return (ConstNumber){.ty = node->ty, .ival = eval_const_expr(node)};

            ConstNumber lhs = eval_const_number(node->lhs);
            ConstNumber rhs = eval_const_number(node->rhs);
            double a = const_number_as_double(lhs);
            double b = const_number_as_double(rhs);
            bool r = node->kind == ND_EQ ? a == b
                   : node->kind == ND_NE ? a != b
                   : node->kind == ND_LT ? a < b
                                         : a <= b;
            return (ConstNumber){.ty = node->ty, .ival = r};
        }
        case ND_LOGAND: {
            ConstNumber lhs = eval_const_number(node->lhs);
            if (!const_number_truth(lhs))
                return (ConstNumber){.ty = node->ty, .ival = 0};
            return (ConstNumber){.ty = node->ty,
                                 .ival = const_number_truth(eval_const_number(node->rhs))};
        }
        case ND_LOGOR: {
            ConstNumber lhs = eval_const_number(node->lhs);
            if (const_number_truth(lhs))
                return (ConstNumber){.ty = node->ty, .ival = 1};
            return (ConstNumber){.ty = node->ty,
                                 .ival = const_number_truth(eval_const_number(node->rhs))};
        }
        case ND_NOT:
            return (ConstNumber){.ty = node->ty,
                                 .ival = !const_number_truth(eval_const_number(node->lhs))};
        case ND_TERNARY: {
            Node *chosen = const_number_truth(eval_const_number(node->cond))
                               ? node->then
                               : node->els;
            return const_number_cast(eval_const_number(chosen), node->ty);
        }
        case ND_CAST:
            return const_number_cast(eval_const_number(node->lhs), node->ty);
        default:
            return (ConstNumber){.ty = node->ty, .ival = eval_const_expr(node)};
        }
    }

    if (!is_flonum(node->ty))
        error("not an arithmetic constant expression");

    switch (node->kind) {
    case ND_NUM:
        return (ConstNumber){.ty = node->ty, .is_fp = true,
                             .fval = node->ty->kind == TY_FLOAT
                                         ? (double)(float)node->fval
                                         : node->fval};
    case ND_NEG: {
        ConstNumber v = const_number_cast(eval_const_number(node->lhs), node->ty);
        v.fval = node->ty->kind == TY_FLOAT ? (double)(float)-v.fval : -v.fval;
        return v;
    }
    case ND_ADD:
    case ND_SUB:
    case ND_MUL:
    case ND_DIV: {
        double a = const_number_as_double(eval_const_number(node->lhs));
        double b = const_number_as_double(eval_const_number(node->rhs));
        double r = node->kind == ND_ADD ? a + b
                   : node->kind == ND_SUB ? a - b
                   : node->kind == ND_MUL ? a * b
                                          : a / b;
        if (node->ty->kind == TY_FLOAT)
            r = (double)(float)r;
        return (ConstNumber){.ty = node->ty, .is_fp = true, .fval = r};
    }
    case ND_TERNARY: {
        Node *chosen = const_number_truth(eval_const_number(node->cond))
                           ? node->then
                           : node->els;
        return const_number_cast(eval_const_number(chosen), node->ty);
    }
    case ND_CAST:
        return const_number_cast(eval_const_number(node->lhs), node->ty);
    default:
        error("not an arithmetic constant expression");
    }
}

static double parse_const_double(Token **rest, Token *tok) {
    Node *node = assign(&tok, tok);
    add_type(node);
    if (!is_numeric(node->ty))
        error("static floating initializer requires an arithmetic constant expression");

    ConstNumber value = const_number_cast(eval_const_number(node), ty_double);
    *rest = tok;
    return value.fval;
}
'''

s = s[:start] + new + s[end:]
p.write_text(s)

# Add the focused suite immediately after the existing static integer initializer suite.
p = Path('Makefile')
s = p.read_text()
anchor = '\tbash ./test/static_integer_initializers.sh\n'
if anchor not in s:
    raise SystemExit('Makefile static integer initializer anchor missing')
s = s.replace(anchor, anchor + '\tbash ./test/static_floating_initializers.sh\n', 1)
p.write_text(s)

Path('test/static_floating_initializers.sh').write_text(r'''#!/bin/bash
set -eu

run_case() {
  expected="$1"
  src="$2"
  cat > tmp-static-fp.c <<EOF
$src
EOF
  ./minicc tmp-static-fp.c > tmp-static-fp.s
  cc -o tmp-static-fp tmp-static-fp.s
  ./tmp-static-fp
  got=$?
  if [ "$got" -ne "$expected" ]; then
    echo "expected exit $expected, got $got: $src"
    exit 1
  fi
  echo "OK(static fp): $src"
}

reject_case() {
  src="$1"
  cat > tmp-static-fp-bad.c <<EOF
$src
EOF
  if ./minicc tmp-static-fp-bad.c >/dev/null 2>&1; then
    echo "expected static floating initializer rejection: $src"
    exit 1
  fi
  echo "OK(reject static fp): $src"
}

run_case 0 'double g = 1.5 + 2.25 * 2.0; int main(void) { return g == 6.0 ? 0 : 1; }'
run_case 0 'float g = 1.25f + 2.5f; int main(void) { return g == 3.75f ? 0 : 1; }'
run_case 0 'double g = (double)(1 + 2 * 3); int main(void) { return g == 7.0 ? 0 : 1; }'
run_case 0 'double g = (int)3.9 + 0.5; int main(void) { return g == 3.5 ? 0 : 1; }'
run_case 0 'double g = 0 ? 1.0 / 0.0 : 2.5; int main(void) { return g == 2.5 ? 0 : 1; }'
run_case 0 'double g = (1.5 < 2.0) ? 4.25 : 9.0; int main(void) { return g == 4.25 ? 0 : 1; }'
run_case 0 'double g = (0.0 || 3.0) ? 8.0 : 1.0; int main(void) { return g == 8.0 ? 0 : 1; }'
run_case 0 'double g = 18446744073709551615ULL; int main(void) { return g > 1.8e19 ? 0 : 1; }'
run_case 0 'static double g = (float)(1.0 / 3.0); int main(void) { return g > 0.3333333 && g < 0.3333334 ? 0 : 1; }'
run_case 0 'double a[3] = {1.0 + 2.0, (double)(4 * 2), 1 ? 9.5 : 0.0}; int main(void) { return a[0] == 3.0 && a[1] == 8.0 && a[2] == 9.5 ? 0 : 1; }'
run_case 0 'struct S { double x; float y; }; struct S s = {1.25 + 0.75, 2.0f * 3.0f}; int main(void) { return s.x == 2.0 && s.y == 6.0f ? 0 : 1; }'
run_case 0 'int f(void) { static double x = 1.0 + 2.0 * 4.0; return x == 9.0; } int main(void) { return f() ? 0 : 1; }'
run_case 0 'enum { N = 5 }; double g = N * 0.5; int main(void) { return g == 2.5 ? 0 : 1; }'
run_case 0 'double g = (1.0 == 1.0) + 0.25; int main(void) { return g == 1.25 ? 0 : 1; }'

reject_case 'double x = 1.0; double g = x + 1.0; int main(void) { return 0; }'
reject_case 'double f(void) { return 1.0; } double g = f(); int main(void) { return 0; }'
reject_case 'int x; double g = (double)&x; int main(void) { return 0; }'
reject_case 'double g = (1.0, 2.0); int main(void) { return 0; }'
reject_case 'double g = (1.0 = 2.0); int main(void) { return 0; }'

rm -f tmp-static-fp.c tmp-static-fp.s tmp-static-fp tmp-static-fp-bad.c

echo 'All static floating constant-expression initializer tests passed!'
''')

# Keep README wording lightweight and accurate.
p = Path('README.md')
s = p.read_text()
needle = 'constant-expression'
if needle in s and 'floating constant-expression initializers' not in s:
    s += '\nStatic-storage floating scalars and aggregate floating subobjects accept arithmetic constant-expression initializers, including casts, conditionals, and mixed integer/floating arithmetic.\n'
elif 'floating constant-expression initializers' not in s:
    s += '\nStatic-storage floating constant-expression initializers are supported for scalar and aggregate subobjects.\n'
p.write_text(s)
