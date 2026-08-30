#include "minicc.h"
#include "preprocess_v2.h"
#include <sys/stat.h>

void validate_program(Program *prog);

typedef enum {
    DRIVER_COMPILE_ASSEMBLY,
    DRIVER_PREPROCESS_ONLY,
    DRIVER_DEPENDENCIES_ONLY,
    DRIVER_SYNTAX_ONLY,
} DriverMode;

typedef struct DependencyTarget DependencyTarget;
struct DependencyTarget {
    DependencyTarget *next;
    char *text;
    bool quote_for_make;
};

typedef struct {
    DriverMode mode;
    char *input_path;
    char *output_path;
    char *dependency_output_path;
    DependencyTarget *dependency_targets;
    DependencyTarget *dependency_targets_tail;
    bool dependency_phony;
    bool dependency_side_effect;
    bool dependency_omit_system;
    bool dependency_missing_generated;
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
            "  -fsyntax-only    Check preprocessing, syntax and semantics only\n"
            "  -M               Emit all Make dependencies only\n"
            "  -MM              Emit non-system Make dependencies only\n"
            "  -MD              Compile and also emit all .d dependencies\n"
            "  -MMD             Compile and emit non-system .d dependencies\n"
            "  -MF <file>       Write dependencies to <file>\n"
            "  -MG              Treat missing headers as generated dependencies\n"
            "  -MP              Add phony rules for header prerequisites\n"
            "  -MT <target>     Add an exact dependency rule target\n"
            "  -MQ <target>     Add a Make-quoted dependency rule target\n"
            "  -D<macro>[=<value>]  Define a preprocessor macro (default value: 1)\n"
            "  -U<macro>        Undefine a preprocessor macro\n"
            "  -I<dir>          Add a user header search directory\n"
            "  -iquote <dir>    Add a quote-only header search directory\n"
            "  -isystem <dir>   Add a system header search directory\n"
            "  -idirafter <dir> Add a system header directory searched last\n"
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

static void add_dependency_target(DriverOptions *opts, const char *text,
                                  bool quote_for_make) {
    DependencyTarget *target = calloc(1, sizeof(DependencyTarget));
    target->text = strdup(text);
    target->quote_for_make = quote_for_make;
    if (opts->dependency_targets_tail)
        opts->dependency_targets_tail->next = target;
    else
        opts->dependency_targets = target;
    opts->dependency_targets_tail = target;
}

static DriverOptions parse_options(int argc, char **argv) {
    DriverOptions opts = {.mode = DRIVER_COMPILE_ASSEMBLY};
    bool end_options = false;
    bool saw_E = false;
    bool saw_S = false;
    bool saw_M = false;
    bool saw_MM = false;
    bool saw_MD = false;
    bool saw_MMD = false;
    bool saw_syntax_only = false;

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

        if (!end_options && !strcmp(arg, "-fsyntax-only")) {
            saw_syntax_only = true;
            opts.mode = DRIVER_SYNTAX_ONLY;
            continue;
        }


        if (!end_options && !strcmp(arg, "-M")) {
            saw_M = true;
            opts.mode = DRIVER_DEPENDENCIES_ONLY;
            continue;
        }

        if (!end_options && !strcmp(arg, "-MM")) {
            saw_MM = true;
            opts.mode = DRIVER_DEPENDENCIES_ONLY;
            opts.dependency_omit_system = true;
            continue;
        }

        if (!end_options && !strcmp(arg, "-MD")) {
            saw_MD = true;
            opts.dependency_side_effect = true;
            continue;
        }

        if (!end_options && !strcmp(arg, "-MMD")) {
            saw_MMD = true;
            opts.dependency_side_effect = true;
            opts.dependency_omit_system = true;
            continue;
        }

        if (!end_options && !strcmp(arg, "-MG")) {
            opts.dependency_missing_generated = true;
            preprocess_v2_enable_missing_header_dependencies();
            continue;
        }


        if (!end_options && !strcmp(arg, "-MP")) {
            opts.dependency_phony = true;
            continue;
        }

        if (!end_options && !strcmp(arg, "-MF")) {
            if (++i >= argc)
                error("%s: missing argument after '-MF'", argv[0]);
            if (opts.dependency_output_path)
                error("%s: dependency output file specified more than once", argv[0]);
            opts.dependency_output_path = argv[i];
            continue;
        }

        if (!end_options && !strncmp(arg, "-MF", 3) && arg[3]) {
            if (opts.dependency_output_path)
                error("%s: dependency output file specified more than once", argv[0]);
            opts.dependency_output_path = arg + 3;
            continue;
        }

        if (!end_options && !strcmp(arg, "-MT")) {
            if (++i >= argc)
                error("%s: missing argument after '-MT'", argv[0]);
            add_dependency_target(&opts, argv[i], false);
            continue;
        }

        if (!end_options && !strncmp(arg, "-MT", 3) && arg[3]) {
            add_dependency_target(&opts, arg + 3, false);
            continue;
        }

        if (!end_options && !strcmp(arg, "-MQ")) {
            if (++i >= argc)
                error("%s: missing argument after '-MQ'", argv[0]);
            add_dependency_target(&opts, argv[i], true);
            continue;
        }

        if (!end_options && !strncmp(arg, "-MQ", 3) && arg[3]) {
            add_dependency_target(&opts, arg + 3, true);
            continue;
        }

        if (!end_options && !strcmp(arg, "-D")) {
            if (++i >= argc)
                error("%s: missing argument after '-D'", argv[0]);
            preprocess_v2_add_define(argv[i]);
            continue;
        }

        if (!end_options && !strncmp(arg, "-D", 2) && arg[2]) {
            preprocess_v2_add_define(arg + 2);
            continue;
        }

        if (!end_options && !strcmp(arg, "-U")) {
            if (++i >= argc)
                error("%s: missing argument after '-U'", argv[0]);
            preprocess_v2_add_undef(argv[i]);
            continue;
        }

        if (!end_options && !strncmp(arg, "-U", 2) && arg[2]) {
            preprocess_v2_add_undef(arg + 2);
            continue;
        }

        if (!end_options && !strcmp(arg, "-I")) {
            if (++i >= argc)
                error("%s: missing argument after '-I'", argv[0]);
            preprocess_v2_add_include_path(argv[i]);
            continue;
        }

        if (!end_options && !strncmp(arg, "-I", 2) && arg[2]) {
            preprocess_v2_add_include_path(arg + 2);
            continue;
        }

        if (!end_options && !strcmp(arg, "-iquote")) {
            if (++i >= argc)
                error("%s: missing argument after '-iquote'", argv[0]);
            preprocess_v2_add_quote_include_path(argv[i]);
            continue;
        }

        if (!end_options && !strncmp(arg, "-iquote", 7) && arg[7]) {
            preprocess_v2_add_quote_include_path(arg + 7);
            continue;
        }

        if (!end_options && !strcmp(arg, "-isystem")) {
            if (++i >= argc)
                error("%s: missing argument after '-isystem'", argv[0]);
            preprocess_v2_add_system_include_path(argv[i]);
            continue;
        }

        if (!end_options && !strncmp(arg, "-isystem", 8) && arg[8]) {
            preprocess_v2_add_system_include_path(arg + 8);
            continue;
        }

        if (!end_options && !strcmp(arg, "-idirafter")) {
            if (++i >= argc)
                error("%s: missing argument after '-idirafter'", argv[0]);
            preprocess_v2_add_after_include_path(argv[i]);
            continue;
        }

        if (!end_options && !strncmp(arg, "-idirafter", 10) && arg[10]) {
            preprocess_v2_add_after_include_path(arg + 10);
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

    int dependency_mode_count = (saw_M ? 1 : 0) + (saw_MM ? 1 : 0) +
                                (saw_MD ? 1 : 0) + (saw_MMD ? 1 : 0);
    bool dependency_requested = dependency_mode_count != 0;
    bool dependency_only = saw_M || saw_MM;
    bool dependency_side_effect_requested = saw_MD || saw_MMD;

    if ((saw_E ? 1 : 0) + (saw_S ? 1 : 0) + (saw_syntax_only ? 1 : 0) > 1)
        error("%s: '-E', '-S' and '-fsyntax-only' are mutually exclusive", argv[0]);
    if (saw_M && saw_MD)
        error("%s: '-M' and '-MD' are mutually exclusive", argv[0]);
    if (dependency_mode_count > 1)
        error("%s: '-M', '-MM', '-MD' and '-MMD' are mutually exclusive", argv[0]);
    if (saw_M && (saw_E || saw_S || saw_syntax_only))
        error("%s: '-M' is mutually exclusive with '-E', '-S' and '-fsyntax-only'", argv[0]);
    if (saw_MM && (saw_E || saw_S || saw_syntax_only))
        error("%s: '-MM' is mutually exclusive with '-E', '-S' and '-fsyntax-only'", argv[0]);
    if (saw_MD && (saw_E || saw_syntax_only))
        error("%s: '-MD' is not supported with '-E' or '-fsyntax-only'", argv[0]);
    if (saw_MMD && (saw_E || saw_syntax_only))
        error("%s: '-MMD' is not supported with '-E' or '-fsyntax-only'", argv[0]);
    if ((opts.dependency_output_path || opts.dependency_targets || opts.dependency_phony) &&
        !dependency_requested)
        error("%s: '-MF', '-MP', '-MT' and '-MQ' require '-M' or '-MD' (also '-MM' or '-MMD')", argv[0]);
    if (opts.dependency_missing_generated && !dependency_only)
        error("%s: '-MG' requires dependency-only mode '-M' or '-MM'", argv[0]);
    if (!opts.input_path)
        error("%s: no input file", argv[0]);
    if (dependency_requested && !strcmp(opts.input_path, "-"))
        error("%s: dependency generation requires a named input file", argv[0]);
    if (saw_M && opts.output_path)
        error("%s: '-o' is not supported with '-M'; use '-MF'", argv[0]);
    if (saw_MM && opts.output_path)
        error("%s: '-o' is not supported with '-MM'; use '-MF'", argv[0]);
    if (opts.mode == DRIVER_SYNTAX_ONLY && opts.output_path)
        error("%s: '-o' is not supported with '-fsyntax-only'", argv[0]);
    if (dependency_side_effect_requested && opts.dependency_output_path &&
        !strcmp(opts.dependency_output_path, "-") &&
        (!opts.output_path || !strcmp(opts.output_path, "-")))
        error("%s: dependency output and compiler output cannot both use standard output", argv[0]);
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

static void finish_output(char *path) {
    if (fflush(stdout) == EOF || ferror(stdout)) {
        if (path && strcmp(path, "-"))
            error("failed to write output %s", path);
        error("failed to write output");
    }
}

static char *path_with_extension(const char *path, const char *extension,
                                 bool basename_only) {
    const char *slash = strrchr(path, '/');
    const char *component = slash ? slash + 1 : path;
    const char *base = basename_only ? component : path;
    const char *dot = strrchr(component, '.');
    size_t stem_len = (dot && dot != component) ? (size_t)(dot - base) : strlen(base);
    size_t ext_len = strlen(extension);
    char *result = calloc(1, stem_len + ext_len + 1);
    memcpy(result, base, stem_len);
    memcpy(result + stem_len, extension, ext_len + 1);
    return result;
}

static void write_make_escaped(FILE *out, const char *text) {
    for (const char *p = text; *p; p++) {
        if (*p == '$') {
            fputs("$$", out);
            continue;
        }
        if (*p == ' ' || *p == '\t' || *p == '#' || *p == ':' || *p == '\\')
            fputc('\\', out);
        fputc(*p, out);
    }
}

static char *default_dependency_target(const DriverOptions *opts) {
    if (opts->output_path && strcmp(opts->output_path, "-"))
        return strdup(opts->output_path);
    return path_with_extension(opts->input_path, ".s", true);
}

static char *default_dependency_output(const DriverOptions *opts) {
    if (opts->dependency_output_path)
        return strdup(opts->dependency_output_path);
    if (opts->mode == DRIVER_DEPENDENCIES_ONLY)
        return NULL;
    if (opts->output_path && strcmp(opts->output_path, "-"))
        return path_with_extension(opts->output_path, ".d", false);
    return path_with_extension(opts->input_path, ".d", true);
}

static void emit_dependency_rule(const DriverOptions *opts) {
    char *default_target = opts->dependency_targets ? NULL : default_dependency_target(opts);
    char *path = default_dependency_output(opts);

    if (path && strcmp(path, "-") &&
        (!strcmp(path, opts->input_path) || same_existing_file(path, opts->input_path)))
        error("input and dependency output files must be different");
    if (path && strcmp(path, "-") && opts->output_path && strcmp(opts->output_path, "-") &&
        (!strcmp(path, opts->output_path) || same_existing_file(path, opts->output_path)))
        error("dependency output and compiler output files must be different");

    FILE *out = stdout;
    bool close_out = false;
    if (path && strcmp(path, "-")) {
        out = fopen(path, "w");
        if (!out)
            error("cannot open dependency output %s", path);
        close_out = true;
    }

    if (opts->dependency_targets) {
        bool first = true;
        for (DependencyTarget *target = opts->dependency_targets; target; target = target->next) {
            if (!first)
                fputc(' ', out);
            if (target->quote_for_make)
                write_make_escaped(out, target->text);
            else
                fputs(target->text, out);
            first = false;
        }
    } else {
        write_make_escaped(out, default_target);
    }
    fputc(':', out);
    fputc(' ', out);
    write_make_escaped(out, opts->input_path);
    int count = preprocess_v2_dependency_count();
    for (int i = 0; i < count; i++) {
        const char *dep = preprocess_v2_dependency_at(i);
        if (!dep || (opts->dependency_omit_system &&
                     preprocess_v2_dependency_is_system(i)))
            continue;
        fputc(' ', out);
        write_make_escaped(out, dep);
    }
    fputc('\n', out);

    if (opts->dependency_phony) {
        for (int i = 0; i < count; i++) {
            const char *dep = preprocess_v2_dependency_at(i);
            if (!dep || (opts->dependency_omit_system &&
                         preprocess_v2_dependency_is_system(i)))
                continue;
            fputc('\n', out);
            write_make_escaped(out, dep);
            fputs(":\n", out);
        }
    }

    if (fflush(out) == EOF || ferror(out)) {
        if (path && strcmp(path, "-"))
            error("failed to write dependency output %s", path);
        error("failed to write dependency output");
    }
    if (close_out && fclose(out) == EOF)
        error("failed to close dependency output %s", path);

    free(default_target);
    free(path);
}

int main(int argc, char **argv) {
    DriverOptions opts = parse_options(argc, argv);
    if (opts.exit_after_options)
        return 0;

    char *user_input = read_file(opts.input_path);
    const char *source_name = !strcmp(opts.input_path, "-") ? "<stdin>" : opts.input_path;
    char *preprocessed = preprocess_v2_source(user_input, source_name);

    if (opts.mode == DRIVER_DEPENDENCIES_ONLY) {
        emit_dependency_rule(&opts);
        return 0;
    }

    if (opts.mode == DRIVER_PREPROCESS_ONLY) {
        select_output(opts.output_path);
        fputs(preprocessed, stdout);
        finish_output(opts.output_path);
        return 0;
    }

    Token *tok = tokenize(preprocessed);
    Program *prog = parse(tok);
    validate_program(prog);

    if (opts.dependency_side_effect)
        emit_dependency_rule(&opts);

    if (opts.mode == DRIVER_SYNTAX_ONLY)
        return 0;

    // Delay opening the output until preprocessing, tokenization and parsing
    // have succeeded so a front-end error does not truncate an existing file.
    select_output(opts.output_path);
    codegen(prog);
    finish_output(opts.output_path);

    return 0;
}
