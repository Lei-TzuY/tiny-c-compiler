#include "minicc.h"
#include "preprocess_v2.h"
#include <sys/stat.h>

typedef enum {
    DRIVER_COMPILE_ASSEMBLY,
    DRIVER_PREPROCESS_ONLY,
} DriverMode;

typedef struct {
    DriverMode mode;
    char *input_path;
    char *output_path;
    bool exit_after_options;
} DriverOptions;

static void print_usage(FILE *out, const char *prog) {
    fprintf(out,
            "Usage: %s [options] <input>\n"
            "\n"
            "Compile one C source file to x86-64 assembly.\n"
            "Use '-' as the input or output path for standard input/output.\n"
            "\n"
            "Options:\n"
            "  -E               Preprocess only\n"
            "  -S               Compile to assembly (default)\n"
            "  -o <file>        Write output to <file>\n"
            "  -o<file>         Same as '-o <file>'\n"
            "  -h, --help       Show this help and exit\n"
            "  --version        Show version information and exit\n"
            "  --               End option processing\n",
            prog);
}

static bool same_existing_file(const char *lhs, const char *rhs) {
    struct stat a;
    struct stat b;

    if (!lhs || !rhs || !strcmp(lhs, "-") || !strcmp(rhs, "-"))
        return false;
    if (stat(lhs, &a) || stat(rhs, &b))
        return false;

    return a.st_dev == b.st_dev && a.st_ino == b.st_ino;
}

static DriverOptions parse_options(int argc, char **argv) {
    DriverOptions opts = {.mode = DRIVER_COMPILE_ASSEMBLY};
    bool end_options = false;
    bool saw_E = false;
    bool saw_S = false;

    for (int i = 1; i < argc; i++) {
        char *arg = argv[i];

        if (!end_options && !strcmp(arg, "--")) {
            end_options = true;
            continue;
        }

        if (!end_options && (!strcmp(arg, "-h") || !strcmp(arg, "--help"))) {
            print_usage(stdout, argv[0]);
            opts.exit_after_options = true;
            return opts;
        }

        if (!end_options && !strcmp(arg, "--version")) {
            puts("minicc (tiny-c-compiler) development");
            opts.exit_after_options = true;
            return opts;
        }

        if (!end_options && !strcmp(arg, "-E")) {
            saw_E = true;
            opts.mode = DRIVER_PREPROCESS_ONLY;
            continue;
        }

        if (!end_options && !strcmp(arg, "-S")) {
            saw_S = true;
            opts.mode = DRIVER_COMPILE_ASSEMBLY;
            continue;
        }

        if (!end_options && !strcmp(arg, "-o")) {
            if (++i >= argc)
                error("%s: missing argument after '-o'", argv[0]);
            if (opts.output_path)
                error("%s: output file specified more than once", argv[0]);
            opts.output_path = argv[i];
            continue;
        }

        if (!end_options && !strncmp(arg, "-o", 2) && arg[2]) {
            if (opts.output_path)
                error("%s: output file specified more than once", argv[0]);
            opts.output_path = arg + 2;
            continue;
        }

        if (!end_options && arg[0] == '-' && strcmp(arg, "-"))
            error("%s: unknown option: %s", argv[0], arg);

        if (opts.input_path)
            error("%s: multiple input files are not supported", argv[0]);
        opts.input_path = arg;
    }

    if (saw_E && saw_S)
        error("%s: '-E' and '-S' are mutually exclusive", argv[0]);
    if (!opts.input_path)
        error("%s: no input file", argv[0]);
    if (opts.output_path && strcmp(opts.output_path, "-") &&
        (!strcmp(opts.output_path, opts.input_path) ||
         same_existing_file(opts.output_path, opts.input_path)))
        error("%s: input and output files must be different", argv[0]);

    return opts;
}

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

static void select_output(char *path) {
    if (!path || !strcmp(path, "-"))
        return;
    if (!freopen(path, "w", stdout))
        error("cannot open output %s", path);
}

int main(int argc, char **argv) {
    DriverOptions opts = parse_options(argc, argv);
    if (opts.exit_after_options)
        return 0;

    char *user_input = read_file(opts.input_path);
    const char *source_name = !strcmp(opts.input_path, "-") ? "<stdin>" : opts.input_path;
    char *preprocessed = preprocess_v2_source(user_input, source_name);

    if (opts.mode == DRIVER_PREPROCESS_ONLY) {
        select_output(opts.output_path);
        fputs(preprocessed, stdout);
        return 0;
    }

    Token *tok = tokenize(preprocessed);
    Program *prog = parse(tok);

    // Delay opening the output until preprocessing, tokenization and parsing
    // have succeeded so a front-end error does not truncate an existing file.
    select_output(opts.output_path);
    codegen(prog);

    return 0;
}
