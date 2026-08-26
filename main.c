#include "minicc.h"
#include "preprocess_v2.h"

static char *read_file(char *path) {
    FILE *fp = fopen(path, "r");
    if (!fp)
        error("cannot open %s", path);

    if (fseek(fp, 0, SEEK_END) == -1)
        error("%s: fseek failed", path);
    long file_size = ftell(fp);
    if (file_size == -1)
        error("%s: ftell failed", path);
    size_t size = file_size;
    rewind(fp);

    char *buf = calloc(1, size + 2);
    if (fread(buf, 1, size, fp) != size)
        error("%s: fread failed", path);
    fclose(fp);

    if (size == 0 || buf[size - 1] != '\n')
        buf[size++] = '\n';
    buf[size] = '\0';
    return buf;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        error("%s: invalid number of arguments", argv[0]);
    }

    char *user_input = read_file(argv[1]);
    char *preprocessed = preprocess_v2(user_input);
    Token *tok = tokenize(preprocessed);
    Program *prog = parse(tok);

    codegen(prog);

    return 0;
}
