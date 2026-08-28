from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"missing anchor for {label} in {path}")
    p.write_text(text.replace(old, new, 1))


p = Path("tokenize.c")
text = p.read_text()
marker = "static Type *integer_literal_type(uint64_t val, int base, bool has_u,\n"
if marker not in text:
    raise SystemExit("missing integer literal helper anchor")

helper = r'''static char *scan_decimal_digits(char *p) {
    while (isdigit((unsigned char)*p))
        p++;
    return p;
}

static char *scan_hex_digits(char *p) {
    while (hex_digit_value(*p) >= 0)
        p++;
    return p;
}

// Recognize a C99 floating constant by grammar before handing the validated
// spelling to strtod for conversion.  strtod intentionally accepts a broader
// implementation syntax on some hosts, so it must not decide whether a token
// is a legal C floating constant.
static bool read_floating_literal(char *start, char **rest, double *value,
                                  Type **literal_ty) {
    char *p = start;
    char *body_end;

    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
        p += 2;
        char *before = p;
        p = scan_hex_digits(p);
        bool have_digit = p != before;
        bool has_dot = false;

        if (*p == '.') {
            has_dot = true;
            p++;
            char *after = p;
            p = scan_hex_digits(p);
            have_digit = have_digit || p != after;
        }

        if (!have_digit) {
            if (has_dot || *p == 'p' || *p == 'P')
                error_at(start,
                         "hexadecimal floating constant requires a hexadecimal digit");
            return false;
        }

        // A hexadecimal floating constant always requires a binary exponent.
        // Without a dot or p/P this spelling remains an ordinary hex integer.
        if (*p != 'p' && *p != 'P') {
            if (has_dot)
                error_at(start,
                         "hexadecimal floating constant requires a p/P exponent");
            return false;
        }

        p++;
        if (*p == '+' || *p == '-')
            p++;
        char *exp = p;
        p = scan_decimal_digits(p);
        if (p == exp)
            error_at(start, "floating exponent requires at least one decimal digit");
        body_end = p;
    } else {
        char *before = p;
        p = scan_decimal_digits(p);
        bool have_digit = p != before;
        bool has_dot = false;
        bool has_exp = false;

        if (*p == '.') {
            has_dot = true;
            p++;
            char *after = p;
            p = scan_decimal_digits(p);
            have_digit = have_digit || p != after;
        }

        if (*p == 'e' || *p == 'E') {
            has_exp = true;
            p++;
            if (*p == '+' || *p == '-')
                p++;
            char *exp = p;
            p = scan_decimal_digits(p);
            if (p == exp)
                error_at(start,
                         "floating exponent requires at least one decimal digit");
        }

        if (!has_dot && !has_exp)
            return false;
        if (!have_digit)
            error_at(start, "floating constant requires a decimal digit");
        body_end = p;
    }

    Type *ty = ty_double;
    if (*p == 'f' || *p == 'F') {
        ty = ty_float;
        p++;
    } else if (*p == 'l' || *p == 'L') {
        // The language frontend intentionally does not expose long double yet:
        // the x86-64 backend has no x87 80-bit storage/call ABI lowering.
        error_at(start, "long double floating constants are not supported");
    }

    if (is_ident2(*p))
        error_at(start, "invalid floating suffix");

    errno = 0;
    char *converted;
    double fval = strtod(start, &converted);
    if (converted != body_end)
        error_at(start, "invalid floating constant");

    *rest = p;
    *value = fval;
    *literal_ty = ty;
    return true;
}

'''
text = text.replace(marker, helper + marker, 1)

start_marker = "        // Numeric literal (integer or floating-point)\n"
end_marker = "        // Identifier or keyword\n"
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit("missing numeric literal tokenizer block")

new_block = r'''        // Numeric literal (integer or floating-point)
        if (isdigit((unsigned char)*p) ||
            (*p == '.' && isdigit((unsigned char)p[1]))) {
            char *q = p;
            char *float_end;
            double fval;
            Type *float_ty;

            if (read_floating_literal(p, &float_end, &fval, &float_ty)) {
                p = float_end;
                cur = cur->next = new_token(TK_NUM, q, p);
                cur->line_no = line;
                cur->is_float = true;
                cur->fval = fval;
                cur->ty = float_ty;
                continue;
            }

            int base = 10;
            if (q[0] == '0' && (q[1] == 'x' || q[1] == 'X'))
                base = 16;
            else if (q[0] == '0')
                base = 8;

            errno = 0;
            char *end;
            uint64_t val = strtoull(p, &end, 0);
            if (errno == ERANGE)
                error_at(q, "integer constant is too large");
            if (end == p)
                error_at(q, "invalid integer constant");

            bool has_u = false;
            int long_count = 0;
            for (;;) {
                if ((*end == 'u' || *end == 'U') && !has_u) {
                    has_u = true;
                    end++;
                    continue;
                }
                if ((*end == 'l' || *end == 'L') && long_count == 0) {
                    char first = *end++;
                    long_count = 1;
                    if (*end == first) {
                        long_count = 2;
                        end++;
                    }
                    continue;
                }
                break;
            }

            if (is_ident2(*end))
                error_at(q, "invalid integer suffix or digit");

            cur = cur->next = new_token(TK_NUM, q, end);
            cur->line_no = line;
            cur->val = (int64_t)val;
            cur->ty = integer_literal_type(val, base, has_u, long_count, q);
            p = end;
            continue;
        }

'''
text = text[:start] + new_block + text[end:]
p.write_text(text)

replace_once(
    "Makefile",
    "\tbash ./test/float.sh\n\tbash ./test/float_abi.sh\n",
    "\tbash ./test/float.sh\n\tbash ./test/floating_literals.sh\n\tbash ./test/float_abi.sh\n",
    "floating literal test target",
)

readme = Path("README.md")
lines = readme.read_text().splitlines()
for i, line in enumerate(lines):
    if line.startswith("- **Lexical literals**:"):
        lines[i] = line + (" Floating constants are grammar-validated C99 decimal/hex spellings: "
                           "decimal exponents require digits, hexadecimal floats require a p/P binary exponent, "
                           "and f/F selects float; l/L long-double constants are diagnosed until the backend "
                           "implements the x87 long-double ABI.")
        break
else:
    raise SystemExit("missing README lexical literals bullet")
readme.write_text("\n".join(lines) + "\n")

Path("test/floating_literals.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-floating-literal.c
  ./minicc tmp-floating-literal.c > tmp-floating-literal.s
  cc -o tmp-floating-literal tmp-floating-literal.s
  set +e
  ./tmp-floating-literal
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "floating literal test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(floating literal): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-floating-literal.c
  if ./minicc tmp-floating-literal.c > tmp-floating-literal.s 2>/dev/null; then
    echo "floating literal test unexpectedly accepted invalid input"
    echo "$input"
    exit 1
  fi
  echo "OK(floating literal): rejected invalid input"
}

# Decimal floating constants: fraction, exponent and f/F suffix forms.
assert_run 4  'int main(){return sizeof(1.0f);}'
assert_run 8  'int main(){return sizeof(1e0);}'
assert_run 100 'int main(){return (int)1e2;}'
assert_run 100 'int main(){return (int)1E+2F;}'
assert_run 5  'int main(){return (int)(.5*10);}'
assert_run 7  'int main(){return (int)(1.*7);}'
assert_run 1  'int main(){return (int)(1e-1*10);}'
assert_run 3  'int main(){return _Generic(1e0,double:3,float:4);}'
assert_run 4  'int main(){return _Generic(1e0F,double:3,float:4);}'

# C99 hexadecimal floating constants require a p/P binary exponent.
assert_run 16 'int main(){return (int)0x1p4;}'
assert_run 6  'int main(){return (int)0x1.8p2;}'
assert_run 4  'int main(){return (int)0X.8P+3;}'
assert_run 8  'int main(){return (int)0x1.p3F;}'

# Static initialization uses the same literal token types and values.
assert_run 10 'double x=0x1.4p3; int main(){return (int)x;}'
assert_run 10 'float x=2.5e0F; int main(){return (int)(x*4);}'

# Nearby integer spellings must remain integers, not float-suffix extensions.
assert_run 31 'int main(){return 0x1f;}'
assert_run 8  'int main(){return sizeof(1L);}'
assert_run 32 'int main(){return 0x1e+2;}'

# A suffix alone cannot turn an integer constant into a floating constant.
assert_reject 'int main(){return (int)1f;}'

# Decimal exponent syntax requires at least one exponent digit.
assert_reject 'int main(){return (int)1e;}'
assert_reject 'int main(){return (int)1e+;}'
assert_reject 'int main(){return (int)1e-;}'
assert_reject 'int main(){return (int).5e;}'
assert_reject 'int main(){return (int).5e+;}'

# Hexadecimal floating syntax always requires p/P and valid exponent digits.
assert_reject 'int main(){return (int)0x1.8;}'
assert_reject 'int main(){return (int)0x.8;}'
assert_reject 'int main(){return (int)0x.p1;}'
assert_reject 'int main(){return (int)0x1p;}'
assert_reject 'int main(){return (int)0x1p+;}'
assert_reject 'int main(){return (int)0x1p-;}'

# Floating suffixes are only f/F in the implemented float/double subset.
assert_reject 'int main(){return (int)1.0u;}'
assert_reject 'int main(){return (int)1.0ff;}'
assert_reject 'int main(){return (int)1e2foo;}'
assert_reject 'int main(){return (int)0x1p2u;}'

# Long-double literals are standard C but deliberately firewalled until the
# backend has 80-bit storage and SysV x87 argument/return lowering.
assert_reject 'int main(){return (int)1.0L;}'
assert_reject 'int main(){return (int).5l;}'
assert_reject 'int main(){return (int)0x1p2L;}'

echo 'All floating literal grammar tests passed!'
''')
