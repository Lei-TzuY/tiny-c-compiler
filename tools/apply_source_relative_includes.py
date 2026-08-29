from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"missing anchor for {label} in {path}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "preprocess_v2.c",
    '''static char *read_file_content(char *path) {\n    FILE *fp = fopen(path, "r");\n''',
    '''// Resolve a quoted include relative to the physical source file that\n// contains the directive.  `#line` changes __FILE__/__LINE__ diagnostics but\n// must not redirect the include search base, so callers pass the immutable\n// preprocess_v2_source() source_name rather than current_pp_file/logical_file.\nstatic char *source_relative_include_path(const char *source_name,\n                                          const char *header) {\n    if (!source_name || !header || !*header || header[0] == '/' ||\n        source_name[0] == '<')\n        return NULL;\n\n    const char *slash = strrchr(source_name, '/');\n    if (!slash)\n        return NULL;\n\n    size_t dir_len = (size_t)(slash - source_name + 1);\n    size_t header_len = strlen(header);\n    char *path = calloc(1, dir_len + header_len + 1);\n    memcpy(path, source_name, dir_len);\n    memcpy(path + dir_len, header, header_len);\n    return path;\n}\n\nstatic char *read_file_content(char *path) {\n    FILE *fp = fopen(path, "r");\n''',
    "source-relative include helper",
)

replace_once(
    "preprocess_v2.c",
    '''                char *owned = NULL;\n                const char *content = NULL;\n                if (quote == '\"')\n                    owned = read_file_content(hname);\n                content = owned ? owned : get_builtin_header(hname);\n                if (!content)\n                    error("cannot include %s", hname);\n                char *sub = preprocess_v2_source((char *)content, hname);\n                sb_puts(&out, sub);\n                if (out.len && out.data[out.len - 1] != '\\n')\n                    sb_putc(&out, '\\n');\n                free(sub);\n                free(owned);\n                free(expanded_include);\n''',
    '''                char *owned = NULL;\n                char *resolved_path = NULL;\n                const char *content = NULL;\n                if (quote == '\"') {\n                    // Quoted headers search next to the physical including file\n                    // first. Preserve the historical current-working-directory\n                    // fallback for callers using stdin or deliberately shared\n                    // project-root headers.\n                    resolved_path = source_relative_include_path(source_name, hname);\n                    if (resolved_path)\n                        owned = read_file_content(resolved_path);\n                    if (!owned) {\n                        free(resolved_path);\n                        resolved_path = NULL;\n                        owned = read_file_content(hname);\n                        if (owned)\n                            resolved_path = strdup(hname);\n                    }\n                }\n                content = owned ? owned : get_builtin_header(hname);\n                if (!content)\n                    error("cannot include %s", hname);\n\n                // Recursive quoted includes must inherit the resolved physical\n                // path so their own relative header names are based on the\n                // directory of the header that contains them.\n                const char *included_source = owned ? resolved_path : hname;\n                char *sub = preprocess_v2_source((char *)content, included_source);\n                sb_puts(&out, sub);\n                if (out.len && out.data[out.len - 1] != '\\n')\n                    sb_putc(&out, '\\n');\n                free(sub);\n                free(owned);\n                free(resolved_path);\n                free(expanded_include);\n''',
    "quoted include resolution",
)

replace_once(
    "Makefile",
    '''\tbash ./test/preprocessor_function_invocation.sh\n\tbash ./test/preprocessor_char_constants.sh\n''',
    '''\tbash ./test/preprocessor_function_invocation.sh\n\tbash ./test/preprocessor_char_constants.sh\n\tbash ./test/preprocessor_include_paths.sh\n''',
    "include path regression target",
)

replace_once(
    "README.md",
    '''- **Preprocessor**: object-like and function-like macros, recursive expansion, direct and macro-expanded `#include`, `#define`, `#undef`, `#if/#elif/#else/#endif`, `#ifdef/#ifndef`, `defined`, variadic macros with `__VA_ARGS__`, stringification `#`, token pasting `##`, source line splicing, and `#error`\n''',
    '''- **Preprocessor**: object-like and function-like macros, recursive expansion, direct and macro-expanded `#include`, source-relative quoted-header lookup (including nested headers, independent of `#line` logical filenames), `#define`, `#undef`, `#if/#elif/#else/#endif`, `#ifdef/#ifndef`, `defined`, variadic macros with `__VA_ARGS__`, stringification `#`, token pasting `##`, source line splicing, and `#error`\n''',
    "README quoted include semantics",
)

Path("test/preprocessor_include_paths.sh").write_text(r'''#!/bin/bash
set -eu

compiler="$(pwd)/minicc"
work="include-path-test.$$"
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/project/sub/nested" "$work/sub"

cat > "$work/project/main.c" <<'SRC'
#include "sub/first.h"
#line 400 "virtual/generated.c"
#include "sub/after_line.h"
#include "stdio.h"
#include <stdlib.h>
int main(void) {
    return FIRST + SECOND + THIRD + LOCAL_STDIO - 60;
}
SRC

cat > "$work/project/sub/first.h" <<'SRC'
#define FIRST 11
#include "nested/second.h"
SRC

cat > "$work/project/sub/nested/second.h" <<'SRC'
#define SECOND 13
SRC

cat > "$work/project/sub/after_line.h" <<'SRC'
#include "../shared.h"
SRC

cat > "$work/project/shared.h" <<'SRC'
#define THIRD 17
SRC

# A quoted local header must win over the compiler's builtin fallback header.
cat > "$work/project/stdio.h" <<'SRC'
#define LOCAL_STDIO 19
SRC

# Angle includes must keep using the builtin/system-style path rather than a
# same-directory quoted-header candidate.
cat > "$work/project/stdlib.h" <<'SRC'
#error local stdlib.h must not satisfy an angle include
SRC

# This distractor proves resolution is relative to project/main.c rather than
# to the process current working directory.
cat > "$work/sub/first.h" <<'SRC'
#error cwd-relative header selected before source-relative header
SRC

(
    cd "$work"
    "$compiler" project/main.c > main.s
    cc -o main main.s
    ./main
)
echo 'OK(preprocessor include path): source-relative and nested quoted includes'

# Preprocess-only mode follows the same path semantics and should expose the
# value from the deeply nested header even when invoked outside the source dir.
(
    cd "$work"
    "$compiler" -E project/main.c > preprocessed.c
    grep -q 'return 11 + 13 + 17 + 19 - 60;' preprocessed.c
)
echo 'OK(preprocessor include path): -E uses source-relative include lookup'

echo 'preprocessor include path tests passed'
''')
