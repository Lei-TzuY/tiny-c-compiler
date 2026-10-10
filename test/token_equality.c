#include "../minicc.h"

static int oversized_reads;

// Model the exact accessible string extent and report a named failure instead
// of performing the invalid read. All comparator RHS values are C strings.
static int bounded_memcmp(const void *lhs, const void *rhs, size_t count) {
    if (count > strlen(rhs) + 1) {
        oversized_reads++;
        return 1;
    }
    return memcmp(lhs, rhs, count);
}

#define memcmp bounded_memcmp
#include "../tokenize.c"
#undef memcmp

int main(void) {
    struct {
        char *name;
        TokenKind kind;
        char *text;
        char *op;
        bool matches;
    } cases[] = {
        {"long identifier against short keyword", TK_IDENT, "ordinary_name", "if", false},
        {"keyword prefix is not a keyword", TK_IDENT, "iffy", "if", false},
        {"matching keyword", TK_IDENT, "return", "return", true},
        {"short identifier is not a keyword", TK_IDENT, "i", "if", false},
        {"matching short keyword", TK_IDENT, "if", "if", true},
        {"long punctuator against short spelling", TK_PUNCT, "<<=", "<", false},
        {"matching punctuator", TK_PUNCT, "<<=", "<<=", true},
        {"punctuator prefix", TK_PUNCT, "=", "==", false},
        {"left bracket digraph", TK_PUNCT, "<:", "[", true},
        {"right bracket digraph", TK_PUNCT, ":>", "]", true},
        {"left brace digraph", TK_PUNCT, "<%", "{", true},
        {"right brace digraph", TK_PUNCT, "%>", "}", true},
        {"unrelated digraph", TK_PUNCT, "<:", "}", false},
    };
    int failures = 0;
    for (size_t i = 0; i < sizeof(cases) / sizeof(*cases); i++) {
        Token tok = {.kind = cases[i].kind, .loc = cases[i].text,
                     .len = strlen(cases[i].text)};
        oversized_reads = 0;
        bool actual = equal(&tok, cases[i].op);
        if (oversized_reads || actual != cases[i].matches) {
            fprintf(stderr, "FAIL(token equality): %s; oversized reads=%d, match=%d\n",
                    cases[i].name, oversized_reads, actual);
            failures++;
        }
    }
    printf("token equality: %zu cases, %d failures\n",
           sizeof(cases) / sizeof(*cases), failures);
    return failures ? 1 : 0;
}
