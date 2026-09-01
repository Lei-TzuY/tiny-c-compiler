#include "minicc.h"
#include "preprocess_v2.h"
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>

void validate_program(Program *prog);

typedef enum {
    DRIVER_COMPILE_ASSEMBLY,
    DRIVER_COMPILE_OBJECT,
    DRIVER_LINK,
    DRIVER_PREPROCESS_ONLY,
    DRIVER_DEPENDENCIES_ONLY,
    DRIVER_SYNTAX_ONLY,
} DriverMode;

typedef enum {
    INPUT_C,
    INPUT_ASSEMBLY,
    INPUT_OBJECT,
    INPUT_ARCHIVE,
    INPUT_SHARED,
    INPUT_UNKNOWN,
} InputKind;

typedef enum {
    MACRO_DUMP_NONE,
    MACRO_DUMP_FINAL,
    MACRO_DUMP_DEFINITIONS,
    MACRO_DUMP_NAMES,
} MacroDumpMode;

typedef struct DependencyTarget DependencyTarget;
struct DependencyTarget {
    DependencyTarget *next;
    char *text;
    bool quote_for_make;
};

typedef struct {
    DriverMode mode;
    char **input_paths;
    int input_count;
    int input_cap;
    char *input_path; // active translation unit / first input for legacy single-input paths
    char *output_path;
    char *dependency_artifact_path;
    char **linker_args;
    int linker_arg_count;
    int linker_arg_cap;
    char *dependency_output_path;
    DependencyTarget *dependency_targets;
    DependencyTarget *dependency_targets_tail;
    bool dependency_phony;
    bool dependency_side_effect;
    bool dependency_omit_system;
    bool dependency_missing_generated;
    MacroDumpMode macro_dump;
    bool exit_after_options;
} DriverOptions;

static void print_usage(FILE *out, const char *prog) {
    fprintf(out,
            "Usage: %s [options] <input>...\n"
            "\n"
            "Compile C source files to x86-64 assembly, objects, or a linked ELF executable.\n"
            "The legacy single-input default remains assembly on standard output.\n"
            "Use '-' as a C input or textual output path for standard input/output.\n"
            "\n"
            "Options:\n"
            "  -E               Preprocess only\n"
            "  -S               Compile to assembly (default)\n"
            "  -c               Compile/assemble to object file(s)\n"
            "  --link           Compile/assemble/link inputs to an executable\n"
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
            "  --define-macro <macro>[=<value>]  Long form of -D\n"
            "  -U<macro>        Undefine a preprocessor macro\n"
            "  --undefine-macro <macro>  Long form of -U\n"
            "  -I<dir>          Add a user header search directory\n"
            "  --include-directory <dir>  Long form of -I\n"
            "  -iquote <dir>    Add a quote-only header search directory\n"
            "  -isystem <dir>   Add a system header search directory\n"
            "  -idirafter <dir> Add a system header directory searched last\n"
            "  --include-directory-after <dir>  Long form of -idirafter\n"
            "  -nostdinc        Disable builtin standard header search\n"
            "  -include <file>  Process a header before the primary source\n"
            "  -imacros <file>  Import macros from a header before the source\n"
            "  -dM              Dump final macro definitions only (requires -E)\n"
            "  -dD              Emit macro definitions with -E output (requires -E)\n"
            "  -dN              Emit macro names with -E output (requires -E)\n"
            "  -o <file>        Write output to <file>\n"
            "  -o<file>         Same as '-o <file>'\n"
            "  -L<dir>          Pass a library search directory in --link mode\n"
            "  -l<name>         Link a library in --link mode\n"
            "  -Wl,<opts>       Pass comma-separated options to the host linker driver\n"
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

static MacroDumpMode parse_macro_dump_mode(const char *mode, const char *prog) {
    if (!strcmp(mode, "M")) return MACRO_DUMP_FINAL;
    if (!strcmp(mode, "D")) return MACRO_DUMP_DEFINITIONS;
    if (!strcmp(mode, "N")) return MACRO_DUMP_NAMES;
    error("%s: supported macro dump modes are M, D and N", prog);
}


static void add_input_path(DriverOptions *opts, const char *path) {
    if (opts->input_count == opts->input_cap) {
        opts->input_cap = opts->input_cap ? opts->input_cap * 2 : 4;
        opts->input_paths = realloc(opts->input_paths,
                                    sizeof(char *) * (size_t)opts->input_cap);
        if (!opts->input_paths)
            error("out of memory while recording input files");
    }
    opts->input_paths[opts->input_count++] = strdup(path);
}

static void add_linker_arg(DriverOptions *opts, const char *arg) {
    if (opts->linker_arg_count == opts->linker_arg_cap) {
        opts->linker_arg_cap = opts->linker_arg_cap ? opts->linker_arg_cap * 2 : 4;
        opts->linker_args = realloc(opts->linker_args,
                                    sizeof(char *) * (size_t)opts->linker_arg_cap);
        if (!opts->linker_args)
            error("out of memory while recording linker arguments");
    }
    opts->linker_args[opts->linker_arg_count++] = strdup(arg);
}

static bool path_has_suffix(const char *path, const char *suffix) {
    size_t n = strlen(path);
    size_t m = strlen(suffix);
    return n >= m && !strcmp(path + n - m, suffix);
}

static InputKind classify_input(const char *path) {
    if (!strcmp(path, "-") || path_has_suffix(path, ".c"))
        return INPUT_C;
    if (path_has_suffix(path, ".s"))
        return INPUT_ASSEMBLY;
    if (path_has_suffix(path, ".o"))
        return INPUT_OBJECT;
    if (path_has_suffix(path, ".a"))
        return INPUT_ARCHIVE;
    if (path_has_suffix(path, ".so"))
        return INPUT_SHARED;
    return INPUT_UNKNOWN;
}

static DriverOptions parse_options(int argc, char **argv) {
    DriverOptions opts = {.mode = DRIVER_COMPILE_ASSEMBLY};
    bool end_options = false;
    bool saw_E = false;
    bool saw_S = false;
    bool saw_c = false;
    bool saw_link = false;
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

        if (!end_options && (!strcmp(arg, "-dM") ||
                             !strcmp(arg, "-dD") ||
                             !strcmp(arg, "-dN"))) {
            char mode[2] = {arg[2], '\0'};
            opts.macro_dump = parse_macro_dump_mode(mode, argv[0]);
            continue;
        }

        if (!end_options && !strncmp(arg, "--dump=", 7)) {
            opts.macro_dump = parse_macro_dump_mode(arg + 7, argv[0]);
            continue;
        }

        if (!end_options && !strcmp(arg, "--dump")) {
            if (++i >= argc)
                error("%s: missing argument after '--dump'", argv[0]);
            opts.macro_dump = parse_macro_dump_mode(argv[i], argv[0]);
            continue;
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

        if (!end_options && !strcmp(arg, "-c")) {
            saw_c = true;
            opts.mode = DRIVER_COMPILE_OBJECT;
            continue;
        }

        if (!end_options && !strcmp(arg, "--link")) {
            saw_link = true;
            opts.mode = DRIVER_LINK;
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

        if (!end_options && !strcmp(arg, "--define-macro")) {
            if (++i >= argc)
                error("%s: missing argument after '--define-macro'", argv[0]);
            preprocess_v2_add_define(argv[i]);
            continue;
        }

        if (!end_options && !strncmp(arg, "--define-macro=", 15) && arg[15]) {
            preprocess_v2_add_define(arg + 15);
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

        if (!end_options && !strcmp(arg, "--undefine-macro")) {
            if (++i >= argc)
                error("%s: missing argument after '--undefine-macro'", argv[0]);
            preprocess_v2_add_undef(argv[i]);
            continue;
        }

        if (!end_options && !strncmp(arg, "--undefine-macro=", 17) && arg[17]) {
            preprocess_v2_add_undef(arg + 17);
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

        if (!end_options &&
            (!strcmp(arg, "-nostdinc") || !strcmp(arg, "--no-standard-includes"))) {
            preprocess_v2_disable_standard_includes();
            continue;
        }

        if (!end_options && (!strcmp(arg, "-include") || !strcmp(arg, "--include"))) {
            if (++i >= argc)
                error("%s: missing argument after '-include'", argv[0]);
            preprocess_v2_add_forced_include(argv[i]);
            continue;
        }

        if (!end_options && !strncmp(arg, "--include=", 10) && arg[10]) {
            preprocess_v2_add_forced_include(arg + 10);
            continue;
        }

        if (!end_options && !strncmp(arg, "-include", 8) && arg[8]) {
            preprocess_v2_add_forced_include(arg + 8);
            continue;
        }

        if (!end_options && (!strcmp(arg, "-imacros") || !strcmp(arg, "--imacros"))) {
            if (++i >= argc)
                error("%s: missing argument after '-imacros'", argv[0]);
            preprocess_v2_add_imacros(argv[i]);
            continue;
        }

        if (!end_options && !strncmp(arg, "--imacros=", 10) && arg[10]) {
            preprocess_v2_add_imacros(arg + 10);
            continue;
        }

        if (!end_options && !strncmp(arg, "-imacros", 8) && arg[8]) {
            preprocess_v2_add_imacros(arg + 8);
            continue;
        }

        if (!end_options && !strcmp(arg, "--include-directory")) {
            if (++i >= argc)
                error("%s: missing argument after '--include-directory'", argv[0]);
            preprocess_v2_add_include_path(argv[i]);
            continue;
        }

        if (!end_options && !strncmp(arg, "--include-directory=", 20) && arg[20]) {
            preprocess_v2_add_include_path(arg + 20);
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

        if (!end_options && !strcmp(arg, "--include-directory-after")) {
            if (++i >= argc)
                error("%s: missing argument after '--include-directory-after'", argv[0]);
            preprocess_v2_add_after_include_path(argv[i]);
            continue;
        }

        if (!end_options && !strncmp(arg, "--include-directory-after=", 26) && arg[26]) {
            preprocess_v2_add_after_include_path(arg + 26);
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

        if (!end_options &&
            ((!strncmp(arg, "-L", 2) && arg[2]) ||
             (!strncmp(arg, "-l", 2) && arg[2]) ||
             !strncmp(arg, "-Wl,", 4))) {
            add_linker_arg(&opts, arg);
            continue;
        }

        if (!end_options && arg[0] == '-' && strcmp(arg, "-"))
            error("%s: unknown option: %s", argv[0], arg);

        add_input_path(&opts, arg);
    }

    if (opts.input_count)
        opts.input_path = opts.input_paths[0];

    int dependency_mode_count = (saw_M ? 1 : 0) + (saw_MM ? 1 : 0) +
                                (saw_MD ? 1 : 0) + (saw_MMD ? 1 : 0);
    bool dependency_requested = dependency_mode_count != 0;
    bool dependency_only = saw_M || saw_MM;
    bool dependency_side_effect_requested = saw_MD || saw_MMD;

    int legacy_output_mode_count = (saw_E ? 1 : 0) + (saw_S ? 1 : 0) +
                                   (saw_syntax_only ? 1 : 0);
    if (legacy_output_mode_count > 1 && !saw_c && !saw_link)
        error("%s: '-E', '-S' and '-fsyntax-only' are mutually exclusive", argv[0]);
    if (legacy_output_mode_count + (saw_c ? 1 : 0) + (saw_link ? 1 : 0) > 1)
        error("%s: '-E', '-S', '-c', '--link' and '-fsyntax-only' are mutually exclusive", argv[0]);
    if (saw_M && saw_MD)
        error("%s: '-M' and '-MD' are mutually exclusive", argv[0]);
    if (dependency_mode_count > 1)
        error("%s: '-M', '-MM', '-MD' and '-MMD' are mutually exclusive", argv[0]);
    if (saw_M && (saw_E || saw_S || saw_c || saw_link || saw_syntax_only))
        error("%s: '-M' is mutually exclusive with compiler output modes", argv[0]);
    if (saw_MM && (saw_E || saw_S || saw_c || saw_link || saw_syntax_only))
        error("%s: '-MM' is mutually exclusive with compiler output modes", argv[0]);
    if (saw_MD && (saw_E || saw_syntax_only))
        error("%s: '-MD' is not supported with '-E' or '-fsyntax-only'", argv[0]);
    if (saw_MMD && (saw_E || saw_syntax_only))
        error("%s: '-MMD' is not supported with '-E' or '-fsyntax-only'", argv[0]);
    if ((saw_MD || saw_MMD) && saw_link)
        error("%s: '-MD' and '-MMD' are not supported with '--link'", argv[0]);
    if ((opts.dependency_output_path || opts.dependency_targets || opts.dependency_phony) &&
        !dependency_requested)
        error("%s: '-MF', '-MP', '-MT' and '-MQ' require '-M' or '-MD' (also '-MM' or '-MMD')", argv[0]);
    if (opts.dependency_missing_generated && !dependency_only)
        error("%s: '-MG' requires dependency-only mode '-M' or '-MM'", argv[0]);
    if (opts.macro_dump == MACRO_DUMP_FINAL && !saw_E)
        error("%s: '-dM' requires '-E'", argv[0]);
    if ((opts.macro_dump == MACRO_DUMP_DEFINITIONS ||
         opts.macro_dump == MACRO_DUMP_NAMES) && !saw_E)
        error("%s: macro dump options require '-E'", argv[0]);
    if (!opts.input_count)
        error("%s: no input file", argv[0]);
    if (opts.input_count > 1 && !saw_E && !saw_S && !saw_c && !saw_link &&
        !saw_syntax_only && !dependency_only)
        error("%s: multiple input files are not supported", argv[0]);
    if (opts.input_count > 1 && (saw_E || dependency_only))
        error("%s: multiple inputs are not supported with '-E', '-M' or '-MM'", argv[0]);
    for (int i = 0; i < opts.input_count; i++)
        if (dependency_requested && !strcmp(opts.input_paths[i], "-"))
            error("%s: dependency generation requires a named input file", argv[0]);
    if (opts.input_count > 1 && opts.output_path &&
        (opts.mode == DRIVER_COMPILE_ASSEMBLY || opts.mode == DRIVER_COMPILE_OBJECT))
        error("%s: cannot use '-o' with multiple inputs in '-S' or '-c' mode", argv[0]);
    if (opts.input_count > 1 &&
        (opts.dependency_output_path || opts.dependency_targets))
        error("%s: '-MF', '-MT' and '-MQ' are ambiguous with multiple inputs", argv[0]);
    if (opts.mode == DRIVER_LINK && opts.dependency_side_effect)
        error("%s: dependency side effects are not supported with '--link'", argv[0]);
    if (opts.linker_arg_count && opts.mode != DRIVER_LINK)
        error("%s: '-L', '-l' and '-Wl,' options require '--link'", argv[0]);
    if (opts.mode == DRIVER_LINK && opts.output_path && !strcmp(opts.output_path, "-"))
        error("%s: linked executable output cannot be standard output", argv[0]);
    if (opts.mode == DRIVER_COMPILE_OBJECT && opts.output_path && !strcmp(opts.output_path, "-"))
        error("%s: object output cannot be standard output", argv[0]);
    if (opts.mode == DRIVER_COMPILE_OBJECT && opts.input_count == 1 &&
        !strcmp(opts.input_path, "-") && !opts.output_path)
        error("%s: '-c' from standard input requires '-o <file>'", argv[0]);
    if (opts.input_count > 1)
        for (int i = 0; i < opts.input_count; i++)
            if (!strcmp(opts.input_paths[i], "-"))
                error("%s: standard input cannot be combined with other inputs", argv[0]);
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
    if (opts.output_path && strcmp(opts.output_path, "-")) {
        for (int i = 0; i < opts.input_count; i++)
            if (!strcmp(opts.output_path, opts.input_paths[i]) ||
                same_existing_file(opts.output_path, opts.input_paths[i]))
                error("%s: input and output files must be different", argv[0]);
    }

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

typedef struct {
    int saved_stdout;
    const char *path;
} OutputScope;

static OutputScope begin_output(const char *path) {
    OutputScope scope = {.saved_stdout = -1, .path = path};
    if (!path || !strcmp(path, "-"))
        return scope;

    if (fflush(stdout) == EOF)
        error("failed to flush compiler output");
    scope.saved_stdout = dup(STDOUT_FILENO);
    if (scope.saved_stdout < 0)
        error("failed to save standard output");

    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd < 0)
        error("cannot open output %s", path);
    if (dup2(fd, STDOUT_FILENO) < 0)
        error("cannot redirect output %s", path);
    close(fd);
    clearerr(stdout);
    return scope;
}

static void end_output(OutputScope *scope) {
    if (fflush(stdout) == EOF || ferror(stdout)) {
        if (scope->path && strcmp(scope->path, "-"))
            error("failed to write output %s", scope->path);
        error("failed to write output");
    }
    if (scope->saved_stdout >= 0) {
        if (dup2(scope->saved_stdout, STDOUT_FILENO) < 0)
            error("failed to restore standard output");
        close(scope->saved_stdout);
        scope->saved_stdout = -1;
        clearerr(stdout);
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
    const char *artifact = opts->dependency_artifact_path
                               ? opts->dependency_artifact_path
                               : opts->output_path;
    if (artifact && strcmp(artifact, "-"))
        return strdup(artifact);
    return path_with_extension(opts->input_path, ".s", true);
}

static char *default_dependency_output(const DriverOptions *opts) {
    if (opts->dependency_output_path)
        return strdup(opts->dependency_output_path);
    if (opts->mode == DRIVER_DEPENDENCIES_ONLY)
        return NULL;
    const char *artifact = opts->dependency_artifact_path
                               ? opts->dependency_artifact_path
                               : opts->output_path;
    if (artifact && strcmp(artifact, "-"))
        return path_with_extension(artifact, ".d", false);
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

typedef struct TempPath TempPath;
struct TempPath {
    TempPath *next;
    char *path;
};

static TempPath *temp_paths;

static void cleanup_temp_paths(void) {
    while (temp_paths) {
        TempPath *next = temp_paths->next;
        unlink(temp_paths->path);
        free(temp_paths->path);
        free(temp_paths);
        temp_paths = next;
    }
}

static char *remember_temp_path(const char *path) {
    TempPath *tmp = calloc(1, sizeof(TempPath));
    tmp->path = strdup(path);
    tmp->next = temp_paths;
    temp_paths = tmp;
    return tmp->path;
}

static char *new_temp_path(void) {
    char tmpl[] = "/tmp/minicc-XXXXXX";
    int fd = mkstemp(tmpl);
    if (fd < 0)
        error("failed to create temporary file");
    close(fd);
    return remember_temp_path(tmpl);
}

static char *new_output_temp_path(const char *output) {
    size_t size = strlen(output) + sizeof(".tmp.XXXXXX");
    char *tmpl = calloc(1, size);
    snprintf(tmpl, size, "%s.tmp.XXXXXX", output);

    int fd = mkstemp(tmpl);
    if (fd < 0)
        error("failed to create temporary output next to %s", output);

    mode_t mask = umask(0);
    umask(mask);
    if (fchmod(fd, 0666 & ~mask) < 0) {
        close(fd);
        unlink(tmpl);
        error("failed to set temporary output permissions for %s", output);
    }
    close(fd);

    char *path = remember_temp_path(tmpl);
    free(tmpl);
    return path;
}

static const char *host_cc(void) {
    const char *cc = getenv("CC");
    return cc && *cc ? cc : "cc";
}

static void run_command(char *const argv[]) {
    pid_t pid = fork();
    if (pid < 0)
        error("failed to fork external tool");
    if (pid == 0) {
        execvp(argv[0], argv);
        _exit(127);
    }

    int status;
    while (waitpid(pid, &status, 0) < 0) {
        if (errno == EINTR)
            continue;
        error("failed waiting for external tool");
    }
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        if (WIFEXITED(status))
            error("external command '%s' failed with exit status %d",
                  argv[0], WEXITSTATUS(status));
        error("external command '%s' terminated by signal", argv[0]);
    }
}

static int run_frontend(DriverOptions *opts) {
    char *user_input = read_file(opts->input_path);
    const char *source_name = !strcmp(opts->input_path, "-") ? "<stdin>" : opts->input_path;
    char *preprocessed = preprocess_v2_source(user_input, source_name);

    if (opts->mode == DRIVER_DEPENDENCIES_ONLY) {
        emit_dependency_rule(opts);
        return 0;
    }

    if (opts->mode == DRIVER_PREPROCESS_ONLY) {
        OutputScope out = begin_output(opts->output_path);
        if (opts->macro_dump == MACRO_DUMP_FINAL) {
            char *dump = preprocess_v2_dump_macros();
            fputs(dump, stdout);
            free(dump);
        } else {
            fputs(preprocessed, stdout);
        }
        end_output(&out);
        return 0;
    }

    Token *tok = tokenize(preprocessed);
    Program *prog = parse(tok);
    validate_program(prog);

    if (opts->dependency_side_effect)
        emit_dependency_rule(opts);

    if (opts->mode == DRIVER_SYNTAX_ONLY)
        return 0;

    // Delay opening the output until the complete front end has succeeded, so
    // an invalid translation unit cannot truncate an existing assembly/object.
    OutputScope out = begin_output(opts->output_path);
    codegen(prog);
    end_output(&out);
    return 0;
}

static void assemble_file(const char *assembly, const char *object) {
    char *temporary = new_output_temp_path(object);
    char *argv[] = {(char *)host_cc(), "-x", "assembler", "-c",
                    (char *)assembly, "-o", temporary, NULL};
    run_command(argv);
    if (rename(temporary, object) < 0)
        error("failed to replace object output %s", object);
}

static void compile_c_to_object(const DriverOptions *opts, const char *input,
                                const char *object) {
    char *assembly = new_temp_path();
    DriverOptions unit = *opts;
    unit.mode = DRIVER_COMPILE_ASSEMBLY;
    unit.input_path = (char *)input;
    unit.output_path = assembly;
    unit.dependency_artifact_path = (char *)object;
    unit.macro_dump = MACRO_DUMP_NONE;
    run_frontend(&unit);
    assemble_file(assembly, object);
}

static void compile_input_to_object(const DriverOptions *opts, const char *input,
                                    const char *object) {
    InputKind kind = classify_input(input);
    if (kind == INPUT_C) {
        compile_c_to_object(opts, input, object);
        return;
    }
    if (kind == INPUT_ASSEMBLY) {
        if (opts->dependency_side_effect)
            error("dependency side effects require C source inputs");
        assemble_file(input, object);
        return;
    }
    error("unsupported input '%s' for '-c'; expected .c or .s", input);
}

static char *default_output_for(const char *input, const char *ext) {
    if (!strcmp(input, "-"))
        error("standard input requires an explicit output path in this mode");
    return path_with_extension(input, ext, true);
}

static void reject_default_output_collision(const DriverOptions *opts, int index,
                                            const char *ext, const char *output) {
    for (int i = 0; i < index; i++) {
        char *previous = default_output_for(opts->input_paths[i], ext);
        bool same = !strcmp(previous, output);
        free(previous);
        if (same)
            error("multiple inputs would write the same default output '%s'", output);
    }
}

static int run_multi_assembly(DriverOptions *opts) {
    for (int i = 0; i < opts->input_count; i++) {
        const char *input = opts->input_paths[i];
        if (classify_input(input) != INPUT_C)
            error("'-S' multi-input mode accepts only C source files: %s", input);
        char *output = default_output_for(input, ".s");
        reject_default_output_collision(opts, i, ".s", output);
        DriverOptions unit = *opts;
        unit.input_path = (char *)input;
        unit.output_path = output;
        unit.dependency_artifact_path = output;
        run_frontend(&unit);
        free(output);
    }
    return 0;
}

static int run_multi_syntax(DriverOptions *opts) {
    for (int i = 0; i < opts->input_count; i++) {
        if (classify_input(opts->input_paths[i]) != INPUT_C)
            error("'-fsyntax-only' accepts only C source files: %s", opts->input_paths[i]);
        DriverOptions unit = *opts;
        unit.input_path = opts->input_paths[i];
        unit.output_path = NULL;
        unit.dependency_artifact_path = NULL;
        run_frontend(&unit);
    }
    return 0;
}

static int run_object_mode(DriverOptions *opts) {
    for (int i = 0; i < opts->input_count; i++) {
        const char *input = opts->input_paths[i];
        char *owned_output = NULL;
        const char *output = opts->output_path;
        if (!output) {
            owned_output = default_output_for(input, ".o");
            reject_default_output_collision(opts, i, ".o", owned_output);
            output = owned_output;
        }
        compile_input_to_object(opts, input, output);
        free(owned_output);
    }
    return 0;
}

static int run_link_mode(DriverOptions *opts) {
    const char *output = opts->output_path ? opts->output_path : "a.out";
    int max_items = opts->input_count + opts->linker_arg_count + 4;
    char **argv = calloc((size_t)max_items, sizeof(char *));
    int n = 0;
    argv[n++] = (char *)host_cc();

    for (int i = 0; i < opts->input_count; i++) {
        const char *input = opts->input_paths[i];
        InputKind kind = classify_input(input);
        if (kind == INPUT_C || kind == INPUT_ASSEMBLY) {
            char *object = new_temp_path();
            DriverOptions unit = *opts;
            unit.dependency_side_effect = false;
            unit.dependency_artifact_path = NULL;
            compile_input_to_object(&unit, input, object);
            argv[n++] = object;
            continue;
        }
        if (kind == INPUT_OBJECT || kind == INPUT_ARCHIVE || kind == INPUT_SHARED) {
            argv[n++] = (char *)input;
            continue;
        }
        error("unsupported link input '%s'; expected .c, .s, .o, .a or .so", input);
    }

    for (int i = 0; i < opts->linker_arg_count; i++)
        argv[n++] = opts->linker_args[i];
    argv[n++] = "-o";
    argv[n++] = (char *)output;
    argv[n] = NULL;
    run_command(argv);
    free(argv);
    return 0;
}

int main(int argc, char **argv) {
    atexit(cleanup_temp_paths);
    DriverOptions opts = parse_options(argc, argv);
    if (opts.exit_after_options)
        return 0;

    if (opts.macro_dump == MACRO_DUMP_DEFINITIONS)
        preprocess_v2_set_dump_mode(PREPROCESS_DUMP_DEFINITIONS);
    else if (opts.macro_dump == MACRO_DUMP_NAMES)
        preprocess_v2_set_dump_mode(PREPROCESS_DUMP_NAMES);

    if (opts.mode == DRIVER_COMPILE_OBJECT)
        return run_object_mode(&opts);
    if (opts.mode == DRIVER_LINK)
        return run_link_mode(&opts);
    if (opts.mode == DRIVER_SYNTAX_ONLY && opts.input_count > 1)
        return run_multi_syntax(&opts);
    if (opts.mode == DRIVER_COMPILE_ASSEMBLY && opts.input_count > 1)
        return run_multi_assembly(&opts);

    // Preprocess/dependency-only multi-input combinations are rejected during
    // option validation. All remaining paths preserve the legacy single-TU
    // behavior, including default assembly on stdout when -o is absent.
    return run_frontend(&opts);
}
