#include "minicc.h"
#include <errno.h>
#include <limits.h>

// Input string
static char *current_input;

// Reports an error and exit.
_Noreturn void error(char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    exit(1);
}

// Reports an error location with line number and context.
_Noreturn void error_at(char *loc, char *fmt, ...) {
    // Find the start of the line containing `loc`
    char *line_start = loc;
    while (line_start > current_input && line_start[-1] != '\n')
        line_start--;

    // Find the end of the line
    char *line_end = loc;
    while (*line_end && *line_end != '\n')
        line_end++;

    // Count line number
    int line_no = 1;
    for (char *p = current_input; p < line_start; p++)
        if (*p == '\n') line_no++;

    // Column (0-based)
    int col = (int)(loc - line_start);

    // Print file location
    fprintf(stderr, "error at line %d:\n", line_no);
    // Print the source line
    fprintf(stderr, "  %.*s\n", (int)(line_end - line_start), line_start);
    // Print the caret
    fprintf(stderr, "  %*s^ ", col, "");
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    exit(1);
}

// Consumes the current token if it matches `op`.
bool equal(Token *tok, char *op) {
    return memcmp(tok->loc, op, tok->len) == 0 && op[tok->len] == '\0';
}

// Ensure that the current token is `op`.
Token *skip(Token *tok, char *op) {
    if (!equal(tok, op))
        error_at(tok->loc, "expected '%s'", op);
    return tok->next;
}

bool consume(Token **rest, Token *tok, char *str) {
    if (equal(tok, str)) {
        *rest = tok->next;
        return true;
    }
    *rest = tok;
    return false;
}

// Create a new token.
static Token *new_token(TokenKind kind, char *start, char *end) {
    Token *tok = calloc(1, sizeof(Token));
    tok->kind = kind;
    tok->loc = start;
    tok->len = end - start;
    return tok;
}

static bool startswith(char *p, char *q) {
    return strncmp(p, q, strlen(q)) == 0;
}

static int hex_digit_value(char c) {
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

static int read_punct(char *p) {
    if (startswith(p, "<<=") || startswith(p, ">>=") || startswith(p, "..."))
        return 3;

    if (startswith(p, "==") || startswith(p, "!=") ||
        startswith(p, "->") ||
        startswith(p, "<=") || startswith(p, ">=") ||
        startswith(p, "&&") || startswith(p, "||") ||
        startswith(p, "++") || startswith(p, "--") ||
        startswith(p, "+=") || startswith(p, "-=") ||
        startswith(p, "*=") || startswith(p, "/=") ||
        startswith(p, "%=") || startswith(p, "&=") ||
        startswith(p, "|=") || startswith(p, "^=") ||
        startswith(p, "<<") || startswith(p, ">>"))
        return 2;

    return ispunct(*p) ? 1 : 0;
}

static bool is_ident1(char c) {
    return ('a' <= c && c <= 'z') || ('A' <= c && c <= 'Z') || c == '_';
}

static bool is_ident2(char c) {
    return is_ident1(c) || ('0' <= c && c <= '9');
}

static bool is_keyword(Token *tok) {
    static char *kw[] = {"return", "int", "char", "if", "else", "while", "for",
                         "void", "break", "continue", "do", "sizeof",
                         "switch", "case", "default", "enum",
                         "struct", "typedef", "union",
                         "short", "long", "unsigned", "goto",
                         "static", "extern", "const", "volatile",
                         "inline", "register", "_Bool", "float", "double"};

    for (int i = 0; i < sizeof(kw) / sizeof(*kw); i++)
        if (equal(tok, kw[i]))
            return true;
    return false;
}

static void convert_keywords(Token *tok) {
    for (Token *t = tok; t->kind != TK_EOF; t = t->next)
        if (t->kind == TK_IDENT && is_keyword(t))
            t->kind = TK_KEYWORD;
}

// Merge adjacent string literal tokens: "abc" "def" -> "abcdef"
static void concat_adjacent_strings(Token *tok) {
    for (Token *t = tok; t && t->next; ) {
        if (t->kind == TK_STR && t->next->kind == TK_STR) {
            Token *next = t->next;
            int len1 = t->ty->array_len - 1;   // exclude null
            int len2 = next->ty->array_len - 1;
            char *buf = calloc(1, len1 + len2 + 1);
            memcpy(buf, t->str, len1);
            memcpy(buf + len1, next->str, len2);
            buf[len1 + len2] = '\0';
            t->str = buf;
            t->ty = array_of(ty_char, len1 + len2 + 1);
            t->len = (int)(next->loc + next->len - t->loc);
            t->next = next->next;
            // Don't advance — check for more concatenations
        } else {
            t = t->next;
        }
    }
}

static Type *integer_literal_type(uint64_t val, int base, bool has_u,
                                  int long_count, char *loc) {
    bool decimal = base == 10;

    if (long_count == 0 && !has_u) {
        if (val <= INT_MAX)
            return ty_int;
        if (!decimal && val <= UINT_MAX)
            return ty_uint;
        if (val <= INT64_MAX)
            return ty_long;
        if (!decimal)
            return ty_ulong;
        error_at(loc, "decimal integer constant is too large for signed long long");
    }

    if (long_count == 0 && has_u)
        return val <= UINT_MAX ? ty_uint : ty_ulong;

    if (long_count == 1 && !has_u) {
        if (val <= INT64_MAX)
            return ty_long;
        if (!decimal)
            return ty_ulong;
        error_at(loc, "decimal long constant is too large");
    }

    if (long_count == 1 && has_u)
        return ty_ulong;

    if (long_count == 2 && !has_u) {
        if (val <= INT64_MAX)
            return ty_llong;
        if (!decimal)
            return ty_ullong;
        error_at(loc, "decimal long long constant is too large");
    }

    if (long_count == 2 && has_u)
        return ty_ullong;

    error_at(loc, "invalid integer suffix");
}

// Tokenize a given string and returns new tokens.
Token *tokenize(char *p) {
    current_input = p;
    Token head = {};
    Token *cur = &head;
    int line = 1;

    while (*p) {
        // Skip whitespace characters.
        if (isspace(*p)) {
            if (*p == '\n') line++;
            p++;
            continue;
        }

        // Skip line comment.
        if (startswith(p, "//")) {
            p += 2;
            while (*p && *p != '\n')
                p++;
            continue;
        }

        // Skip block comment.
        if (startswith(p, "/*")) {
            char *q = strstr(p + 2, "*/");
            if (!q)
                error_at(p, "unclosed block comment");
            // Count newlines inside block comment
            for (char *s = p; s < q + 2; s++)
                if (*s == '\n') line++;
            p = q + 2;
            continue;
        }

        // Numeric literal (integer or floating-point)
        if (isdigit(*p) || (*p == '.' && isdigit(p[1]))) {
            char *q = p;
            bool hex = p[0] == '0' && (p[1] == 'x' || p[1] == 'X');

            // Let strtod identify decimal/hex floating syntax.  In a hex
            // integer, e/E are ordinary digits, so only p/P denotes an exponent.
            char *fend;
            double fval = strtod(p, &fend);
            bool is_flonum = *p == '.';
            for (char *c = p; c < fend; c++) {
                if (*c == '.' || (!hex && (*c == 'e' || *c == 'E')) ||
                    (hex && (*c == 'p' || *c == 'P'))) {
                    is_flonum = true;
                    break;
                }
            }
            bool is_float_suffix = false;
            if (*fend == 'f' || *fend == 'F') {
                is_flonum = true;
                is_float_suffix = true;
                fend++;
            }

            if (is_flonum) {
                if (is_ident2(*fend))
                    error_at(q, "invalid floating suffix");
                p = fend;
                cur = cur->next = new_token(TK_NUM, q, p);
                cur->line_no = line;
                cur->is_float = true;
                cur->fval = fval;
                cur->ty = is_float_suffix ? ty_float : ty_double;
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

        // Identifier or keyword
        if (is_ident1(*p)) {
            char *start = p;
            do {
                p++;
            } while (is_ident2(*p));
            cur = cur->next = new_token(TK_IDENT, start, p);
            cur->line_no = line;
            continue;
        }

        // String literal
        if (*p == '"') {
            char *start = p++;
            char *buf = calloc(1, strlen(p) + 1);
            int len = 0;
            while (*p != '"') {
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
            buf[len] = '\0';
            cur = cur->next = new_token(TK_STR, start, p + 1);
            cur->line_no = line;
            cur->str = buf;
            cur->ty = array_of(ty_char, len + 1);
            p++;
            continue;
        }

        // Char literal
        if (*p == '\'') {
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
            p++;
            cur = cur->next = new_token(TK_NUM, start, p);
            cur->line_no = line;
            cur->val = val;
            continue;
        }

        // Punctuators
        int punct_len = read_punct(p);
        if (punct_len) {
            cur = cur->next = new_token(TK_PUNCT, p, p + punct_len);
            cur->line_no = line;
            p += punct_len;
            continue;
        }

        error_at(p, "invalid token");
    }

    cur = cur->next = new_token(TK_EOF, p, p);
    cur->line_no = line;
    convert_keywords(head.next);
    concat_adjacent_strings(head.next);
    return head.next;
}
