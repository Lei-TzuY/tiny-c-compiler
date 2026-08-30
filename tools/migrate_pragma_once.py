from pathlib import Path

pp = Path("preprocess_v2.c")
text = pp.read_text()

include_old = '#include "preprocess_v2.h"\n#include <errno.h>\n'
include_new = '#include "preprocess_v2.h"\n#include <errno.h>\n#include <sys/types.h>\n#include <sys/stat.h>\n'
if '#include <sys/stat.h>' not in text:
    if include_old not in text:
        raise SystemExit('preprocess include marker not found')
    text = text.replace(include_old, include_new, 1)

struct_marker = '''struct CliMacroAction {
    CliMacroAction *next;
    CliMacroKind kind;
    char *arg;
};

static void parse_define(char *start);
'''
struct_replacement = '''struct CliMacroAction {
    CliMacroAction *next;
    CliMacroKind kind;
    char *arg;
};

typedef struct OnceFile OnceFile;
struct OnceFile {
    OnceFile *next;
    bool has_stat;
    dev_t dev;
    ino_t ino;
    char *name;
};

static void parse_define(char *start);
'''
if 'typedef struct OnceFile OnceFile;' not in text:
    if struct_marker not in text:
        raise SystemExit('once-file struct marker not found')
    text = text.replace(struct_marker, struct_replacement, 1)

static_marker = '''static CliMacroAction *cli_macro_actions;
static CliMacroAction *cli_macro_actions_tail;
'''
static_replacement = '''static CliMacroAction *cli_macro_actions;
static CliMacroAction *cli_macro_actions_tail;
static OnceFile *once_files;
'''
if 'static OnceFile *once_files;' not in text:
    if static_marker not in text:
        raise SystemExit('once-file static marker not found')
    text = text.replace(static_marker, static_replacement, 1)

ident_marker = '''static bool is_ident2_pp(char c) {
    return isalnum((unsigned char)c) || c == '_';
}

static void queue_cli_macro_action(CliMacroKind kind, const char *arg) {
'''
ident_replacement = '''static bool is_ident2_pp(char c) {
    return isalnum((unsigned char)c) || c == '_';
}

static bool stat_source(const char *source_name, struct stat *st) {
    return source_name && source_name[0] != '<' && stat(source_name, st) == 0;
}

static bool once_contains_source(const char *source_name) {
    struct stat st;
    bool has_stat = stat_source(source_name, &st);

    for (OnceFile *file = once_files; file; file = file->next) {
        if (has_stat && file->has_stat) {
            if (file->dev == st.st_dev && file->ino == st.st_ino)
                return true;
            continue;
        }
        if (!has_stat && !file->has_stat && file->name && source_name &&
            !strcmp(file->name, source_name))
            return true;
    }
    return false;
}

static void mark_once_source(const char *source_name) {
    if (!source_name || once_contains_source(source_name))
        return;

    OnceFile *file = calloc(1, sizeof(OnceFile));
    struct stat st;
    file->has_stat = stat_source(source_name, &st);
    if (file->has_stat) {
        file->dev = st.st_dev;
        file->ino = st.st_ino;
    } else {
        file->name = strdup(source_name);
    }
    file->next = once_files;
    once_files = file;
}

static void clear_once_files(void) {
    while (once_files) {
        OnceFile *next = once_files->next;
        free(once_files->name);
        free(once_files);
        once_files = next;
    }
}

static void queue_cli_macro_action(CliMacroKind kind, const char *arg) {
'''
if 'static bool once_contains_source' not in text:
    if ident_marker not in text:
        raise SystemExit('once helper insertion marker not found')
    text = text.replace(ident_marker, ident_replacement, 1)

outer_marker = '''    bool outermost = preprocess_depth++ == 0;
    if (outermost) {
        add_macro(strdup("__STDC__"), true, false, NULL, 0, strdup("1"));
'''
outer_replacement = '''    bool outermost = preprocess_depth++ == 0;
    if (outermost) {
        clear_once_files();
        add_macro(strdup("__STDC__"), true, false, NULL, 0, strdup("1"));
'''
if '        clear_once_files();\n        add_macro(strdup("__STDC__")' not in text:
    if outer_marker not in text:
        raise SystemExit('outermost initialization marker not found')
    text = text.replace(outer_marker, outer_replacement, 1)

pragma_marker = '''            } else if (is_cond_active() && !strcmp(directive, "undef")) {
                char *name = read_directive_ident(&start);
                if (!name) error("expected identifier after #undef");
                undef_macro(name);
                free(name);
            } else if (is_cond_active() && !strcmp(directive, "include")) {
'''
pragma_replacement = '''            } else if (is_cond_active() && !strcmp(directive, "undef")) {
                char *name = read_directive_ident(&start);
                if (!name) error("expected identifier after #undef");
                undef_macro(name);
                free(name);
            } else if (is_cond_active() && !strcmp(directive, "pragma")) {
                // #pragma is implementation-defined.  Support the ubiquitous
                // once form and deliberately ignore unknown pragmas.
                char *pragma = read_directive_ident(&start);
                if (pragma && !strcmp(pragma, "once"))
                    mark_once_source(source_name);
                free(pragma);
            } else if (is_cond_active() && !strcmp(directive, "include")) {
'''
if '!strcmp(directive, "pragma")' not in text:
    if pragma_marker not in text:
        raise SystemExit('pragma insertion marker not found')
    text = text.replace(pragma_marker, pragma_replacement, 1)

include_marker = '''                // Recursive quoted includes must inherit the resolved physical
                // path so their own relative header names are based on the
                // directory of the header that contains them.
                const char *included_source = owned ? resolved_path : hname;
                char *sub = preprocess_v2_source((char *)content, included_source);
                sb_puts(&out, sub);
                if (out.len && out.data[out.len - 1] != '\\n')
                    sb_putc(&out, '\\n');
                free(sub);
                free(owned);
'''
include_replacement = '''                // Recursive quoted includes must inherit the resolved physical
                // path so their own relative header names are based on the
                // directory of the header that contains them.  A file that has
                // already executed #pragma once is skipped by physical identity
                // (device/inode when available), not merely by path spelling.
                const char *included_source = owned ? resolved_path : hname;
                if (!once_contains_source(included_source)) {
                    char *sub = preprocess_v2_source((char *)content, included_source);
                    sb_puts(&out, sub);
                    if (out.len && out.data[out.len - 1] != '\\n')
                        sb_putc(&out, '\\n');
                    free(sub);
                }
                free(owned);
'''
if 'already executed #pragma once' not in text:
    if include_marker not in text:
        raise SystemExit('include recursion marker not found')
    text = text.replace(include_marker, include_replacement, 1)

end_marker = '''    preprocess_depth--;
    current_pp_file = saved_file;
    current_pp_line = saved_line;
    free(logical_file);
    return out.data;
}
'''
end_replacement = '''    preprocess_depth--;
    current_pp_file = saved_file;
    current_pp_line = saved_line;
    free(logical_file);
    if (outermost)
        clear_once_files();
    return out.data;
}
'''
if '    if (outermost)\n        clear_once_files();\n    return out.data;' not in text:
    if end_marker not in text:
        raise SystemExit('outermost cleanup marker not found')
    text = text.replace(end_marker, end_replacement, 1)

pp.write_text(text)

makefile = Path('Makefile')
mk = makefile.read_text()
needle = '\tbash ./test/preprocessor_include_paths.sh\n'
entry = '\tbash ./test/preprocessor_pragma_once.sh\n'
if entry not in mk:
    if needle not in mk:
        raise SystemExit('Makefile preprocessor include-path entry not found')
    makefile.write_text(mk.replace(needle, needle + entry, 1))

Path('test/preprocessor_pragma_once.sh').write_text(r'''#!/bin/bash
set -eu

fail() {
  echo "FAIL(#pragma once): $*" >&2
  exit 1
}

cleanup() {
  rm -rf tmp-pragma-once
  rm -f tmp-pragma-once-*.c tmp-pragma-once-*.i tmp-pragma-once-*.s tmp-pragma-once-*.out
}
trap cleanup EXIT

mkdir -p tmp-pragma-once/sub

# A directly repeated include must only contribute the header once.
cat > tmp-pragma-once/direct.h <<'EOF'
#pragma once
enum { DIRECT_ONCE_VALUE = 17 };
EOF
cat > tmp-pragma-once-direct.c <<'EOF'
#include "tmp-pragma-once/direct.h"
#include "tmp-pragma-once/direct.h"
int main(void) { return DIRECT_ONCE_VALUE == 17 ? 0 : 1; }
EOF
./minicc tmp-pragma-once-direct.c > tmp-pragma-once-direct.s
cc -o tmp-pragma-once-direct.out tmp-pragma-once-direct.s
./tmp-pragma-once-direct.out || fail 'direct repeated include was not deduplicated'

# Marking happens as soon as the active pragma is encountered, so a header can
# include itself after #pragma once without recursing forever.
cat > tmp-pragma-once/self.h <<'EOF'
#pragma once
#include "self.h"
enum { SELF_ONCE_VALUE = 23 };
EOF
cat > tmp-pragma-once-self.c <<'EOF'
#include "tmp-pragma-once/self.h"
int main(void) { return SELF_ONCE_VALUE == 23 ? 0 : 1; }
EOF
./minicc tmp-pragma-once-self.c > tmp-pragma-once-self.s
cc -o tmp-pragma-once-self.out tmp-pragma-once-self.s
./tmp-pragma-once-self.out || fail 'self include was not stopped by #pragma once'

# Diamond inclusion must collapse the common physical header to one expansion.
cat > tmp-pragma-once/base.h <<'EOF'
#pragma once
enum { DIAMOND_BASE_VALUE = 31 };
EOF
cat > tmp-pragma-once/left.h <<'EOF'
#include "base.h"
enum { DIAMOND_LEFT_VALUE = 1 };
EOF
cat > tmp-pragma-once/right.h <<'EOF'
#include "base.h"
enum { DIAMOND_RIGHT_VALUE = 2 };
EOF
cat > tmp-pragma-once-diamond.c <<'EOF'
#include "tmp-pragma-once/left.h"
#include "tmp-pragma-once/right.h"
int main(void) {
  return DIAMOND_BASE_VALUE == 31 && DIAMOND_LEFT_VALUE == 1 &&
         DIAMOND_RIGHT_VALUE == 2 ? 0 : 1;
}
EOF
./minicc tmp-pragma-once-diamond.c > tmp-pragma-once-diamond.s
cc -o tmp-pragma-once-diamond.out tmp-pragma-once-diamond.s
./tmp-pragma-once-diamond.out || fail 'diamond include duplicated the common header'

# Identity is physical, not textual.  #line changes the logical diagnostic file
# name but must not affect once identity; dot/dot-dot spellings, symlinks, and
# hardlinks of the same inode must all be skipped after the first inclusion.
cat > tmp-pragma-once/alias.h <<'EOF'
#line 400 "virtual-alias.h"
#pragma once
enum { ALIAS_ONCE_VALUE = 47 };
EOF
ln -s alias.h tmp-pragma-once/alias-link.h
ln tmp-pragma-once/alias.h tmp-pragma-once/alias-hard.h
cat > tmp-pragma-once-alias.c <<'EOF'
#include "tmp-pragma-once/alias.h"
#include "./tmp-pragma-once/sub/../alias.h"
#include "tmp-pragma-once/alias-link.h"
#include "tmp-pragma-once/alias-hard.h"
int main(void) { return ALIAS_ONCE_VALUE == 47 ? 0 : 1; }
EOF
./minicc tmp-pragma-once-alias.c > tmp-pragma-once-alias.s
cc -o tmp-pragma-once-alias.out tmp-pragma-once-alias.s
./tmp-pragma-once-alias.out || fail 'physical path aliases were not deduplicated'

# A pragma in an inactive conditional branch has no effect.
cat > tmp-pragma-once/inactive.h <<'EOF'
#if 0
#pragma once
#endif
#ifndef SECOND_PASS
int inactive_first_marker;
#else
int inactive_second_marker;
#endif
EOF
cat > tmp-pragma-once-inactive.c <<'EOF'
#include "tmp-pragma-once/inactive.h"
#define SECOND_PASS 1
#include "tmp-pragma-once/inactive.h"
EOF
./minicc -E tmp-pragma-once-inactive.c > tmp-pragma-once-inactive.i
grep -F 'int inactive_first_marker;' tmp-pragma-once-inactive.i >/dev/null || \
  fail 'first inactive-pragma include disappeared'
grep -F 'int inactive_second_marker;' tmp-pragma-once-inactive.i >/dev/null || \
  fail 'inactive #pragma once incorrectly suppressed the second include'

# Unknown implementation pragmas remain ignored and do not acquire once
# semantics accidentally.
cat > tmp-pragma-once/unknown.h <<'EOF'
#pragma vendor_extension once
int unknown_pragma_marker;
EOF
cat > tmp-pragma-once-unknown.c <<'EOF'
#include "tmp-pragma-once/unknown.h"
#include "tmp-pragma-once/unknown.h"
EOF
./minicc -E tmp-pragma-once-unknown.c > tmp-pragma-once-unknown.i
count=$(grep -F -c 'int unknown_pragma_marker;' tmp-pragma-once-unknown.i || true)
[ "$count" -eq 2 ] || fail "unknown pragma changed include behavior (count=$count)"

echo 'All #pragma once tests passed!'
''')
