from pathlib import Path

p = Path('tokenize.c')
s = p.read_text()
old = r'''static int read_escaped_char(char c) {
    switch (c) {
    case 'n': return '\n';
    case 't': return '\t';
    case 'r': return '\r';
    case '\\': return '\\';
    case '"': return '"';
    case '\'': return '\'';
    case '0': return '\0';
    case 'a': return '\a';
    case 'b': return '\b';
    case 'f': return '\f';
    case 'v': return '\v';
    default: return c;
    }
}
'''
new = r'''static int hex_digit_value(char c) {
    if ('0' <= c && c <= '9') return c - '0';
    if ('a' <= c && c <= 'f') return c - 'a' + 10;
    if ('A' <= c && c <= 'F') return c - 'A' + 10;
    return -1;
}

// Read one escape sequence after the leading backslash.  Ordinary character
// and string literals use the execution character set represented by a byte in
// this compiler, so numeric escape values must fit in unsigned char.
static int read_escaped_char(char **rest, char *p, char *start) {
    if ('0' <= *p && *p <= '7') {
        unsigned val = 0;
        int digits = 0;
        while (digits < 3 && '0' <= *p && *p <= '7') {
            val = (val << 3) + (*p - '0');
            p++;
            digits++;
        }
        if (val > UCHAR_MAX)
            error_at(start, "octal escape sequence is out of range");
        *rest = p;
        return (int)val;
    }

    if (*p == 'x') {
        p++;
        int digit = hex_digit_value(*p);
        if (digit < 0)
            error_at(start, "hex escape sequence requires a hexadecimal digit");

        unsigned val = 0;
        while ((digit = hex_digit_value(*p)) >= 0) {
            if (val > UCHAR_MAX / 16 || val * 16u + (unsigned)digit > UCHAR_MAX)
                error_at(start, "hex escape sequence is out of range");
            val = val * 16u + (unsigned)digit;
            p++;
        }
        *rest = p;
        return (int)val;
    }

    char c = *p++;
    *rest = p;
    switch (c) {
    case 'n': return '\n';
    case 't': return '\t';
    case 'r': return '\r';
    case '\\': return '\\';
    case '"': return '"';
    case '\'': return '\'';
    case 'a': return '\a';
    case 'b': return '\b';
    case 'f': return '\f';
    case 'v': return '\v';
    case '?': return '?';
    default: return (unsigned char)c;
    }
}
'''
if s.count(old) != 1:
    raise SystemExit(f'escape helper anchor count={s.count(old)}')
s = s.replace(old, new, 1)
old = r'''            while (*p != '"') {
                if (!*p) error_at(start, "unclosed string literal");
                if (*p == '\\') { p++; buf[len++] = read_escaped_char(*p++); }
                else             buf[len++] = *p++;
            }
'''
new = r'''            while (*p != '"') {
                if (!*p) error_at(start, "unclosed string literal");
                if (*p == '\n') error_at(start, "newline in string literal");
                if (*p == '\\') {
                    p++;
                    if (!*p || *p == '\n')
                        error_at(start, "unclosed escape sequence in string literal");
                    buf[len++] = read_escaped_char(&p, p, start);
                } else {
                    buf[len++] = *p++;
                }
            }
'''
if s.count(old) != 1:
    raise SystemExit(f'string literal anchor count={s.count(old)}')
s = s.replace(old, new, 1)
old = r'''        if (*p == '\'') {
            char *start = p++;
            int val;
            if (*p == '\\') { p++; val = read_escaped_char(*p++); }
            else if (*p == '\'') error_at(start, "empty char literal");
            else val = (unsigned char)*p++;
            if (*p != '\'') error_at(start, "unclosed char literal");
'''
new = r'''        if (*p == '\'') {
            char *start = p++;
            int val;
            if (*p == '\\') {
                p++;
                if (!*p || *p == '\n')
                    error_at(start, "unclosed escape sequence in char literal");
                val = read_escaped_char(&p, p, start);
            } else if (*p == '\'') {
                error_at(start, "empty char literal");
            } else if (!*p || *p == '\n') {
                error_at(start, "unclosed char literal");
            } else {
                val = (unsigned char)*p++;
            }
            if (*p != '\'') error_at(start, "unclosed char literal");
'''
if s.count(old) != 1:
    raise SystemExit(f'char literal anchor count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('Makefile')
s = p.read_text()
needle = '\tbash ./test/integer_literals.sh\n'
if s.count(needle) != 1:
    raise SystemExit(f'Makefile anchor count={s.count(needle)}')
s = s.replace(needle, needle + '\tbash ./test/escape_sequences.sh\n', 1)
p.write_text(s)

p = Path('README.md')
s = p.read_text()
needle = '- **Preprocessor**: object-like and function-like macros, recursive expansion, `#include`, `#define`, `#undef`, `#if/#elif/#else/#endif`, `#ifdef/#ifndef`, `defined`, variadic macros with `__VA_ARGS__`, stringification `#`, token pasting `##`, source line splicing, and `#error`\n'
replacement = '- **Lexical literals**: ordinary character/string literals support standard simple escapes plus one-to-three-digit octal and variable-length hexadecimal escapes, with byte-range diagnostics and adjacent string literal concatenation\n' + needle
if s.count(needle) != 1:
    raise SystemExit(f'README anchor count={s.count(needle)}')
p.write_text(s.replace(needle, replacement, 1))

Path('test/escape_sequences.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-escape.c
  ./minicc tmp-escape.c > tmp-escape.s
  cc -o tmp-escape tmp-escape.s
  set +e
  ./tmp-escape
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "escape sequence failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(escape sequence): $actual"
}

assert_fail() {
  input="$1"
  printf "%b" "$input" > tmp-escape-bad.c
  if ./minicc tmp-escape-bad.c > tmp-escape-bad.s 2>/dev/null; then
    echo "escape sequence unexpectedly accepted invalid program"
    printf "%b\n" "$input"
    exit 1
  fi
  echo "OK(escape sequence): rejected invalid program"
}

# Numeric character escapes.
assert_run 65 "int main(){return '\\101';}"
assert_run 65 "int main(){return '\\x41';}"
assert_run 255 "int main(){return '\\377';}"
assert_run 127 "int main(){return '\\x7f';}"
assert_run 0 "int main(){return '\\000';}"

# Numeric escapes inside strings consume exactly the C-defined span.
assert_run 65 'int main(){char *s="\101B";return s[0];}'
assert_run 66 'int main(){char *s="\101B";return s[1];}'
assert_run 66 'int main(){char *s="\x41" "B";return s[1];}'
assert_run 4 'int main(){return sizeof("A\0B");}'
assert_run 0 'int main(){char *s="\0007";return s[0];}'
assert_run 55 'int main(){char *s="\0007";return s[1];}'

# Standard simple escapes remain supported, including question mark.
assert_run 10 "int main(){return '\\n';}"
assert_run 9 "int main(){return '\\t';}"
assert_run 63 "int main(){return '\\?';}"
assert_run 34 'int main(){char *s="\"";return s[0];}'
assert_run 92 'int main(){char *s="\\\\";return s[0];}'

# Ill-formed or out-of-range numeric escapes are diagnosed lexically.
assert_fail "int main(){return '\\\\x';}\n"
assert_fail "int main(){return '\\\\400';}\n"
assert_fail "int main(){return '\\\\x100';}\n"
assert_fail 'int main(){char *s="\x";return 0;}\n'
assert_fail 'int main(){char *s="\400";return 0;}\n'
assert_fail 'int main(){char *s="\x100";return 0;}\n'

# Raw newlines cannot appear inside ordinary character/string literals.
assert_fail 'int main(){char *s="abc\ndef";return 0;}\n'
assert_fail "int main(){return 'a\n';}\n"

echo 'All escape-sequence tests passed!'
''')
