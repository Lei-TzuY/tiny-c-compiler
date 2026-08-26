#include "minicc.h"

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

static int read_escaped_char(char c) {
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
            char *end;
            double fval = strtod(p, &end);
            // Check if floating-point constant (contains '.', 'e', 'E', or 'f'/'F' suffix)
            bool is_flonum = false;
            for (char *c = p; c < end; c++) {
                if (*c == '.' || *c == 'e' || *c == 'E') {
                    is_flonum = true;
                    break;
                }
            }
            bool is_float_suffix = false;
            if (*end == 'f' || *end == 'F') {
                is_flonum = true;
                is_float_suffix = true;
                end++;
            }

            if (is_flonum) {
                p = end;
                cur = cur->next = new_token(TK_NUM, q, p);
                cur->line_no = line;
                cur->is_float = true;
                cur->fval = fval;
                cur->ty = is_float_suffix ? ty_float : ty_double;
                continue;
            }

            // Integer literal
            cur = cur->next = new_token(TK_NUM, p, p);
            cur->line_no = line;
            cur->val = strtoul(p, &p, 0);
            cur->len = p - q;
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
                if (*p == '\\') { p++; buf[len++] = read_escaped_char(*p++); }
                else             buf[len++] = *p++;
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
            if (*p == '\\') { p++; val = read_escaped_char(*p++); }
            else if (*p == '\'') error_at(start, "empty char literal");
            else val = (unsigned char)*p++;
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
