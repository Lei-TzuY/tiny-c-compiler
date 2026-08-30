from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


# ---- preprocess_v2.h -------------------------------------------------------
h = Path("preprocess_v2.h")
text = h.read_text()
text = replace_once(
    text,
    "void preprocess_v2_add_undef(const char *name);\n",
    "void preprocess_v2_add_undef(const char *name);\n"
    "int preprocess_v2_dependency_count(void);\n"
    "const char *preprocess_v2_dependency_at(int index);\n",
    "preprocessor dependency API",
)
h.write_text(text)


# ---- preprocess_v2.c -------------------------------------------------------
pp = Path("preprocess_v2.c")
text = pp.read_text()

text = replace_once(
    text,
    "typedef struct OnceFile OnceFile;\n"
    "struct OnceFile {\n"
    "    OnceFile *next;\n"
    "    bool has_stat;\n"
    "    dev_t dev;\n"
    "    ino_t ino;\n"
    "    char *name;\n"
    "};\n",
    "typedef struct OnceFile OnceFile;\n"
    "struct OnceFile {\n"
    "    OnceFile *next;\n"
    "    bool has_stat;\n"
    "    dev_t dev;\n"
    "    ino_t ino;\n"
    "    char *name;\n"
    "};\n\n"
    "typedef struct Dependency Dependency;\n"
    "struct Dependency {\n"
    "    Dependency *next;\n"
    "    bool has_stat;\n"
    "    dev_t dev;\n"
    "    ino_t ino;\n"
    "    char *path;\n"
    "};\n",
    "dependency struct",
)

text = replace_once(
    text,
    "static CliMacroAction *cli_macro_actions_tail;\n"
    "static OnceFile *once_files;\n",
    "static CliMacroAction *cli_macro_actions_tail;\n"
    "static OnceFile *once_files;\n"
    "static Dependency *dependencies;\n"
    "static Dependency *dependencies_tail;\n",
    "dependency globals",
)

marker = "static void clear_once_files(void) {\n    while (once_files) {\n        OnceFile *next = once_files->next;\n        free(once_files->name);\n        free(once_files);\n        once_files = next;\n    }\n}\n"
insert = marker + r'''

static void clear_dependencies(void) {
    while (dependencies) {
        Dependency *next = dependencies->next;
        free(dependencies->path);
        free(dependencies);
        dependencies = next;
    }
    dependencies_tail = NULL;
}

static void record_dependency(const char *path) {
    if (!path || !*path)
        return;

    struct stat st;
    bool has_stat = stat_source(path, &st);
    for (Dependency *dep = dependencies; dep; dep = dep->next) {
        if (has_stat && dep->has_stat) {
            if (dep->dev == st.st_dev && dep->ino == st.st_ino)
                return;
            continue;
        }
        if (!has_stat && !dep->has_stat && !strcmp(dep->path, path))
            return;
    }

    Dependency *dep = calloc(1, sizeof(Dependency));
    dep->has_stat = has_stat;
    if (has_stat) {
        dep->dev = st.st_dev;
        dep->ino = st.st_ino;
    }
    dep->path = strdup(path);
    if (dependencies_tail)
        dependencies_tail->next = dep;
    else
        dependencies = dep;
    dependencies_tail = dep;
}

int preprocess_v2_dependency_count(void) {
    int count = 0;
    for (Dependency *dep = dependencies; dep; dep = dep->next)
        count++;
    return count;
}

const char *preprocess_v2_dependency_at(int index) {
    if (index < 0)
        return NULL;
    for (Dependency *dep = dependencies; dep; dep = dep->next)
        if (index-- == 0)
            return dep->path;
    return NULL;
}
'''
text = replace_once(text, marker, insert, "dependency helpers")

text = replace_once(
    text,
    "    if (outermost) {\n"
    "        clear_once_files();\n",
    "    if (outermost) {\n"
    "        clear_once_files();\n"
    "        clear_dependencies();\n",
    "dependency reset",
)

text = replace_once(
    text,
    "                const char *included_source = owned ? resolved_path : hname;\n"
    "                if (!once_contains_source(included_source)) {\n",
    "                const char *included_source = owned ? resolved_path : hname;\n"
    "                if (owned)\n"
    "                    record_dependency(included_source);\n"
    "                if (!once_contains_source(included_source)) {\n",
    "dependency recording",
)
pp.write_text(text)


# ---- main.c ----------------------------------------------------------------
main = Path("main.c")
text = main.read_text()

text = replace_once(
    text,
    "    DRIVER_PREPROCESS_ONLY,\n"
    "    DRIVER_SYNTAX_ONLY,\n",
    "    DRIVER_PREPROCESS_ONLY,\n"
    "    DRIVER_DEPENDENCIES_ONLY,\n"
    "    DRIVER_SYNTAX_ONLY,\n",
    "driver dependency mode",
)

text = replace_once(
    text,
    "    char *output_path;\n"
    "    bool exit_after_options;\n",
    "    char *output_path;\n"
    "    char *dependency_output_path;\n"
    "    char *dependency_target;\n"
    "    bool dependency_side_effect;\n"
    "    bool exit_after_options;\n",
    "driver dependency fields",
)

text = replace_once(
    text,
    "            \"  -fsyntax-only    Check preprocessing, syntax and semantics only\\n\"\n"
    "            \"  -D<macro>[=<value>]  Define a preprocessor macro (default value: 1)\\n\"\n",
    "            \"  -fsyntax-only    Check preprocessing, syntax and semantics only\\n\"\n"
    "            \"  -M               Emit Make dependencies only\\n\"\n"
    "            \"  -MD              Compile and also emit a .d dependency file\\n\"\n"
    "            \"  -MF <file>       Write dependencies to <file>\\n\"\n"
    "            \"  -MT <target>     Set the dependency rule target\\n\"\n"
    "            \"  -D<macro>[=<value>]  Define a preprocessor macro (default value: 1)\\n\"\n",
    "driver help",
)

text = replace_once(
    text,
    "    bool saw_E = false;\n"
    "    bool saw_S = false;\n"
    "    bool saw_syntax_only = false;\n",
    "    bool saw_E = false;\n"
    "    bool saw_S = false;\n"
    "    bool saw_M = false;\n"
    "    bool saw_MD = false;\n"
    "    bool saw_syntax_only = false;\n",
    "driver dependency flags",
)

syntax_block = "        if (!end_options && !strcmp(arg, \"-fsyntax-only\")) {\n            saw_syntax_only = true;\n            opts.mode = DRIVER_SYNTAX_ONLY;\n            continue;\n        }\n"
dep_options = syntax_block + r'''

        if (!end_options && !strcmp(arg, "-M")) {
            saw_M = true;
            opts.mode = DRIVER_DEPENDENCIES_ONLY;
            continue;
        }

        if (!end_options && !strcmp(arg, "-MD")) {
            saw_MD = true;
            opts.dependency_side_effect = true;
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
            if (opts.dependency_target)
                error("%s: dependency target specified more than once", argv[0]);
            opts.dependency_target = argv[i];
            continue;
        }

        if (!end_options && !strncmp(arg, "-MT", 3) && arg[3]) {
            if (opts.dependency_target)
                error("%s: dependency target specified more than once", argv[0]);
            opts.dependency_target = arg + 3;
            continue;
        }
'''
text = replace_once(text, syntax_block, dep_options, "driver dependency options")

old_validation = r'''    if ((saw_E ? 1 : 0) + (saw_S ? 1 : 0) + (saw_syntax_only ? 1 : 0) > 1)
        error("%s: '-E', '-S' and '-fsyntax-only' are mutually exclusive", argv[0]);
    if (!opts.input_path)
        error("%s: no input file", argv[0]);
    if (opts.mode == DRIVER_SYNTAX_ONLY && opts.output_path)
        error("%s: '-o' is not supported with '-fsyntax-only'", argv[0]);
    if (opts.output_path && strcmp(opts.output_path, "-") &&
        (!strcmp(opts.output_path, opts.input_path) ||
         same_existing_file(opts.output_path, opts.input_path)))
        error("%s: input and output files must be different", argv[0]);
'''
new_validation = r'''    if ((saw_E ? 1 : 0) + (saw_S ? 1 : 0) + (saw_syntax_only ? 1 : 0) > 1)
        error("%s: '-E', '-S' and '-fsyntax-only' are mutually exclusive", argv[0]);
    if (saw_M && saw_MD)
        error("%s: '-M' and '-MD' are mutually exclusive", argv[0]);
    if (saw_M && (saw_E || saw_S || saw_syntax_only))
        error("%s: '-M' is mutually exclusive with '-E', '-S' and '-fsyntax-only'", argv[0]);
    if (saw_MD && (saw_E || saw_syntax_only))
        error("%s: '-MD' is not supported with '-E' or '-fsyntax-only'", argv[0]);
    if ((opts.dependency_output_path || opts.dependency_target) && !saw_M && !saw_MD)
        error("%s: '-MF' and '-MT' require '-M' or '-MD'", argv[0]);
    if (!opts.input_path)
        error("%s: no input file", argv[0]);
    if ((saw_M || saw_MD) && !strcmp(opts.input_path, "-"))
        error("%s: dependency generation requires a named input file", argv[0]);
    if (saw_M && opts.output_path)
        error("%s: '-o' is not supported with '-M'; use '-MF'", argv[0]);
    if (opts.mode == DRIVER_SYNTAX_ONLY && opts.output_path)
        error("%s: '-o' is not supported with '-fsyntax-only'", argv[0]);
    if (saw_MD && opts.dependency_output_path && !strcmp(opts.dependency_output_path, "-") &&
        (!opts.output_path || !strcmp(opts.output_path, "-")))
        error("%s: dependency output and compiler output cannot both use standard output", argv[0]);
    if (opts.output_path && strcmp(opts.output_path, "-") &&
        (!strcmp(opts.output_path, opts.input_path) ||
         same_existing_file(opts.output_path, opts.input_path)))
        error("%s: input and output files must be different", argv[0]);
'''
text = replace_once(text, old_validation, new_validation, "driver dependency validation")

main_marker = "int main(int argc, char **argv) {\n"
helpers = r'''static char *path_with_extension(const char *path, const char *extension,
                                 bool basename_only) {
    const char *base = path;
    if (basename_only) {
        const char *slash = strrchr(path, '/');
        if (slash)
            base = slash + 1;
    }

    const char *dot = strrchr(base, '.');
    size_t stem_len = (dot && dot != base) ? (size_t)(dot - base) : strlen(base);
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
    char *target = opts->dependency_target ? strdup(opts->dependency_target)
                                           : default_dependency_target(opts);
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

    write_make_escaped(out, target);
    fputc(':', out);
    fputc(' ', out);
    write_make_escaped(out, opts->input_path);
    int count = preprocess_v2_dependency_count();
    for (int i = 0; i < count; i++) {
        const char *dep = preprocess_v2_dependency_at(i);
        if (!dep)
            continue;
        fputc(' ', out);
        write_make_escaped(out, dep);
    }
    fputc('\n', out);

    if (fflush(out) == EOF || ferror(out)) {
        if (path && strcmp(path, "-"))
            error("failed to write dependency output %s", path);
        error("failed to write dependency output");
    }
    if (close_out && fclose(out) == EOF)
        error("failed to close dependency output %s", path);

    free(target);
    free(path);
}

'''
text = replace_once(text, main_marker, helpers + main_marker, "driver dependency helpers")

text = replace_once(
    text,
    "    char *preprocessed = preprocess_v2_source(user_input, source_name);\n\n"
    "    if (opts.mode == DRIVER_PREPROCESS_ONLY) {\n",
    "    char *preprocessed = preprocess_v2_source(user_input, source_name);\n\n"
    "    if (opts.mode == DRIVER_DEPENDENCIES_ONLY) {\n"
    "        emit_dependency_rule(&opts);\n"
    "        return 0;\n"
    "    }\n\n"
    "    if (opts.mode == DRIVER_PREPROCESS_ONLY) {\n",
    "dependency-only flow",
)

text = replace_once(
    text,
    "    Program *prog = parse(tok);\n"
    "    validate_program(prog);\n\n"
    "    if (opts.mode == DRIVER_SYNTAX_ONLY)\n",
    "    Program *prog = parse(tok);\n"
    "    validate_program(prog);\n\n"
    "    if (opts.dependency_side_effect)\n"
    "        emit_dependency_rule(&opts);\n\n"
    "    if (opts.mode == DRIVER_SYNTAX_ONLY)\n",
    "dependency side effect flow",
)
main.write_text(text)


# ---- Makefile ---------------------------------------------------------------
mk = Path("Makefile")
text = mk.read_text()
text = replace_once(
    text,
    "\tbash ./test/preprocessor_pragma_once.sh\n",
    "\tbash ./test/preprocessor_pragma_once.sh\n"
    "\tbash ./test/dependency_generation.sh\n",
    "dependency regression hook",
)
mk.write_text(text)


# ---- regression -------------------------------------------------------------
Path("test/dependency_generation.sh").write_text(r'''#!/bin/bash
set -eu

fail() {
  echo "FAIL(dependency generation): $*" >&2
  exit 1
}

assert_reject() {
  pattern="$1"
  shift
  if "$@" >tmp-deps-cmd.out 2>tmp-deps-cmd.err; then
    fail "command unexpectedly succeeded: $*"
  fi
  if ! grep -F -- "$pattern" tmp-deps-cmd.err >/dev/null; then
    echo "missing diagnostic: $pattern" >&2
    cat tmp-deps-cmd.err >&2
    exit 1
  fi
}

cleanup() {
  rm -rf tmp-deps-tree 'tmp-deps-space dir'
  rm -f tmp-deps-*.c tmp-deps-*.s tmp-deps-*.d tmp-deps-*.mk \
        tmp-deps-*.out tmp-deps-cmd.out tmp-deps-cmd.err
}
trap cleanup EXIT

./minicc --help > tmp-deps-help.out
grep -F -- '-M' tmp-deps-help.out >/dev/null || fail '--help missing -M'
grep -F -- '-MD' tmp-deps-help.out >/dev/null || fail '--help missing -MD'
grep -F -- '-MF <file>' tmp-deps-help.out >/dev/null || fail '--help missing -MF'
grep -F -- '-MT <target>' tmp-deps-help.out >/dev/null || fail '--help missing -MT'

mkdir -p tmp-deps-tree/sub 'tmp-deps-space dir'
cat > tmp-deps-tree/sub/leaf.h <<'EOF'
#pragma once
#define LEAF_VALUE 7
EOF
cat > tmp-deps-tree/root.h <<'EOF'
#pragma once
#include "sub/leaf.h"
#define ROOT_VALUE (LEAF_VALUE + 1)
EOF
ln -s root.h tmp-deps-tree/root-link.h
ln tmp-deps-tree/root.h tmp-deps-tree/root-hard.h
cat > tmp-deps-tree/extra.h <<'EOF'
#define EXTRA_VALUE 99
EOF
cat > 'tmp-deps-space dir/space header.h' <<'EOF'
#define SPACE_VALUE 3
EOF

cat > tmp-deps-main.c <<'EOF'
#define ROOT_HEADER "tmp-deps-tree/root.h"
#include ROOT_HEADER
#include "tmp-deps-tree/root-link.h"
#include "tmp-deps-tree/root-hard.h"
#include "tmp-deps-tree/sub/../root.h"
#include "tmp-deps-space dir/space header.h"
#include <stddef.h>
#if WANT_EXTRA
#include "tmp-deps-tree/extra.h"
#endif
int main(void) { return ROOT_VALUE == 8 && SPACE_VALUE == 3 ? 0 : 1; }
EOF

# -M performs real preprocessing and reports only physical file dependencies.
# Repeated path aliases of the same inode collapse to one prerequisite, builtin
# headers are not fabricated as filesystem dependencies, and Make metacharacters
# in paths/targets are escaped.
./minicc -M -MT 'build target.s' tmp-deps-main.c > tmp-deps-basic.mk
first=$(head -n 1 tmp-deps-basic.mk)
case "$first" in
  'build\ target.s:'*) ;;
  *) fail "-MT target was not Make-escaped: $first" ;;
esac
grep -F 'tmp-deps-main.c' tmp-deps-basic.mk >/dev/null || fail 'source prerequisite missing'
grep -F 'tmp-deps-tree/root.h' tmp-deps-basic.mk >/dev/null || fail 'root dependency missing'
grep -F 'tmp-deps-tree/sub/leaf.h' tmp-deps-basic.mk >/dev/null || fail 'nested dependency missing'
grep -F 'tmp-deps-space\ dir/space\ header.h' tmp-deps-basic.mk >/dev/null || fail 'space-containing dependency not escaped'
[ "$(grep -o 'tmp-deps-tree/root.h' tmp-deps-basic.mk | wc -l)" -eq 1 ] || fail 'physical header dependency was duplicated'
! grep -F 'root-link.h' tmp-deps-basic.mk >/dev/null || fail 'symlink alias leaked into dependency list'
! grep -F 'root-hard.h' tmp-deps-basic.mk >/dev/null || fail 'hardlink alias leaked into dependency list'
! grep -F 'extra.h' tmp-deps-basic.mk >/dev/null || fail 'inactive include became a dependency'
! grep -F 'stddef.h' tmp-deps-basic.mk >/dev/null || fail 'builtin header became a filesystem dependency'

# Command-line macros influence conditional dependency discovery because -M uses
# the same preprocessor as ordinary compilation.
./minicc -M -DWANT_EXTRA=1 tmp-deps-main.c > tmp-deps-extra.mk
grep -F 'tmp-deps-tree/extra.h' tmp-deps-extra.mk >/dev/null || fail '-D did not affect dependency discovery'
grep -F 'tmp-deps-main.s:' tmp-deps-extra.mk >/dev/null || fail 'default -M target is not source-basename .s'

# -MF supports separated and attached forms and keeps -M dependency output away
# from stdout when a file is requested.
./minicc -M -MF tmp-deps-separated.mk tmp-deps-main.c > tmp-deps-separated.out
test ! -s tmp-deps-separated.out || fail '-M -MF unexpectedly wrote dependencies to stdout'
test -s tmp-deps-separated.mk || fail '-M -MF did not create dependency file'
./minicc -M -MFtmp-deps-attached.mk -MTattached-target tmp-deps-main.c
grep -F 'attached-target:' tmp-deps-attached.mk >/dev/null || fail 'attached -MF/-MT forms failed'

# -MD preserves normal compilation while writing a sidecar next to an explicit
# assembly output. The dependency target defaults to the actual compiler output.
./minicc -MD -o tmp-deps-program.s tmp-deps-main.c
cc -o tmp-deps-program.out tmp-deps-program.s
./tmp-deps-program.out || fail '-MD changed compiled program behavior'
test -s tmp-deps-program.d || fail '-MD did not create output-derived .d file'
grep -F 'tmp-deps-program.s:' tmp-deps-program.d >/dev/null || fail '-MD target did not follow -o'
grep -F 'tmp-deps-tree/sub/leaf.h' tmp-deps-program.d >/dev/null || fail '-MD nested dependency missing'

# Without -o, -MD keeps assembly on stdout and derives the sidecar from the
# source basename. -MF/-MT override both defaults when requested.
./minicc -MD tmp-deps-main.c > tmp-deps-stdout.s
test -s tmp-deps-main.d || fail '-MD without -o did not create source-basename .d'
grep -F 'tmp-deps-main.s:' tmp-deps-main.d >/dev/null || fail '-MD default target is wrong'
./minicc -MD -MF tmp-deps-custom.d -MT custom-target -o tmp-deps-custom.s tmp-deps-main.c
grep -F 'custom-target:' tmp-deps-custom.d >/dev/null || fail '-MF/-MT did not override -MD defaults'
test -s tmp-deps-custom.s || fail '-MD -MF/-MT lost compiler output'

# Invalid combinations are diagnosed rather than silently producing ambiguous
# mixed output or truncating unrelated files.
assert_reject "'-M' and '-MD' are mutually exclusive" ./minicc -M -MD tmp-deps-main.c
assert_reject "'-M' is mutually exclusive" ./minicc -M -S tmp-deps-main.c
assert_reject "'-MD' is not supported with '-E' or '-fsyntax-only'" ./minicc -MD -E tmp-deps-main.c
assert_reject "'-MF' and '-MT' require '-M' or '-MD'" ./minicc -MF tmp-deps-orphan.mk tmp-deps-main.c
assert_reject "'-MF' and '-MT' require '-M' or '-MD'" ./minicc -MT orphan tmp-deps-main.c
assert_reject "missing argument after '-MF'" ./minicc -M -MF
assert_reject "missing argument after '-MT'" ./minicc -M -MT
assert_reject "'-o' is not supported with '-M'; use '-MF'" ./minicc -M -o tmp-deps-bad.mk tmp-deps-main.c
assert_reject 'dependency generation requires a named input file' ./minicc -M -
assert_reject 'dependency output and compiler output cannot both use standard output' \
  ./minicc -MD -MF - tmp-deps-main.c
assert_reject 'input and dependency output files must be different' \
  ./minicc -M -MF tmp-deps-main.c tmp-deps-main.c
assert_reject 'dependency output and compiler output files must be different' \
  ./minicc -MD -MF tmp-deps-same.s -o tmp-deps-same.s tmp-deps-main.c

echo 'All dependency generation tests passed!'
''')
