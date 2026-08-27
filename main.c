#include "minicc.h"
#include "preprocess_v2.h"

static char *read_stream(FILE *fp, char *name) {
    size_t cap = 4096;
    size_t len = 0;
    char *buf = calloc(1, cap);

    for (;;) {
        if (len + 2 > cap) {
            cap *= 2;
            char *new_buf = realloc(buf, cap);
            if (!new_buf) {
                free(buf);
                error("%s: out of memory while reading input", name);
            }
            buf = new_buf;
        }

        size_t n = fread(buf + len, 1, cap - len - 1, fp);
        len += n;
        if (n == 0) {
            if (ferror(fp))
                error("%s: fread failed", name);
            break;
        }
    }

    if (len == 0 || buf[len - 1] != '\n')
        buf[len++] = '\n';
    buf[len] = '\0';
    return buf;
}

static char *read_file(char *path) {
    if (!strcmp(path, "-"))
        return read_stream(stdin, "<stdin>");

    FILE *fp = fopen(path, "r");
    if (!fp)
        error("cannot open %s", path);

    char *buf = read_stream(fp, path);
    fclose(fp);
    return buf;
}

int main(int argc, char **argv) {
    if (argc != 2)
        error("%s: invalid number of arguments", argv[0]);

    char *user_input = read_file(argv[1]);
    char *preprocessed = preprocess_v2(user_input);
    Token *tok = tokenize(preprocessed);
    Program *prog = parse(tok);

    codegen(prog);

    return 0;
}
