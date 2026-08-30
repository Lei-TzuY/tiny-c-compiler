from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


main = Path("main.c")
text = main.read_text()

text = replace_once(
    text,
    "typedef struct {\n"
    "    DriverMode mode;\n",
    "typedef struct DependencyTarget DependencyTarget;\n"
    "struct DependencyTarget {\n"
    "    DependencyTarget *next;\n"
    "    char *text;\n"
    "    bool quote_for_make;\n"
    "};\n\n"
    "typedef struct {\n"
    "    DriverMode mode;\n",
    "dependency target type",
)

text = replace_once(
    text,
    "    char *dependency_output_path;\n"
    "    char *dependency_target;\n"
    "    bool dependency_side_effect;\n",
    "    char *dependency_output_path;\n"
    "    DependencyTarget *dependency_targets;\n"
    "    DependencyTarget *dependency_targets_tail;\n"
    "    bool dependency_phony;\n"
    "    bool dependency_side_effect;\n",
    "dependency target fields",
)

text = replace_once(
    text,
    "            \"  -MF <file>       Write dependencies to <file>\\n\"\n"
    "            \"  -MT <target>     Set the dependency rule target\\n\"\n",
    "            \"  -MF <file>       Write dependencies to <file>\\n\"\n"
    "            \"  -MP              Add phony rules for header prerequisites\\n\"\n"
    "            \"  -MT <target>     Add an exact dependency rule target\\n\"\n"
    "            \"  -MQ <target>     Add a Make-quoted dependency rule target\\n\"\n",
    "dependency help",
)

marker = "static DriverOptions parse_options(int argc, char **argv) {\n"
helper = r'''static void add_dependency_target(DriverOptions *opts, const char *text,
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

'''
text = replace_once(text, marker, helper + marker, "dependency target helper")

md_block = r'''        if (!end_options && !strcmp(arg, "-MD")) {
            saw_MD = true;
            opts.dependency_side_effect = true;
            continue;
        }
'''
text = replace_once(
    text,
    md_block,
    md_block + r'''

        if (!end_options && !strcmp(arg, "-MP")) {
            opts.dependency_phony = true;
            continue;
        }
''',
    "-MP parsing",
)

old_mt = r'''        if (!end_options && !strcmp(arg, "-MT")) {
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
new_mt = r'''        if (!end_options && !strcmp(arg, "-MT")) {
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
'''
text = replace_once(text, old_mt, new_mt, "-MT/-MQ parsing")

text = replace_once(
    text,
    "    if ((opts.dependency_output_path || opts.dependency_target) && !saw_M && !saw_MD)\n"
    "        error(\"%s: '-MF' and '-MT' require '-M' or '-MD'\", argv[0]);\n",
    "    if ((opts.dependency_output_path || opts.dependency_targets || opts.dependency_phony) &&\n"
    "        !saw_M && !saw_MD)\n"
    "        error(\"%s: '-MF', '-MP', '-MT' and '-MQ' require '-M' or '-MD'\", argv[0]);\n",
    "dependency option validation",
)

old_emit_start = r'''static void emit_dependency_rule(const DriverOptions *opts) {
    char *target = opts->dependency_target ? strdup(opts->dependency_target)
                                           : default_dependency_target(opts);
    char *path = default_dependency_output(opts);
'''
new_emit_start = r'''static void emit_dependency_rule(const DriverOptions *opts) {
    char *default_target = opts->dependency_targets ? NULL : default_dependency_target(opts);
    char *path = default_dependency_output(opts);
'''
text = replace_once(text, old_emit_start, new_emit_start, "dependency emit target setup")

old_emit_target = r'''    write_make_escaped(out, target);
    fputc(':', out);
'''
new_emit_target = r'''    if (opts->dependency_targets) {
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
'''
text = replace_once(text, old_emit_target, new_emit_target, "dependency target emission")

old_emit_tail = r'''    fputc('\n', out);

    if (fflush(out) == EOF || ferror(out)) {
'''
new_emit_tail = r'''    fputc('\n', out);

    if (opts->dependency_phony) {
        for (int i = 0; i < count; i++) {
            const char *dep = preprocess_v2_dependency_at(i);
            if (!dep)
                continue;
            fputc('\n', out);
            write_make_escaped(out, dep);
            fputs(":\n", out);
        }
    }

    if (fflush(out) == EOF || ferror(out)) {
'''
text = replace_once(text, old_emit_tail, new_emit_tail, "-MP phony emission")

text = replace_once(text, "    free(target);\n    free(path);\n", "    free(default_target);\n    free(path);\n", "dependency target cleanup")

main.write_text(text)


test = Path("test/dependency_generation.sh")
text = test.read_text()

text = replace_once(
    text,
    "grep -F -- '-MF <file>' tmp-deps-help.out >/dev/null || fail '--help missing -MF'\n"
    "grep -F -- '-MT <target>' tmp-deps-help.out >/dev/null || fail '--help missing -MT'\n",
    "grep -F -- '-MF <file>' tmp-deps-help.out >/dev/null || fail '--help missing -MF'\n"
    "grep -F -- '-MP' tmp-deps-help.out >/dev/null || fail '--help missing -MP'\n"
    "grep -F -- '-MT <target>' tmp-deps-help.out >/dev/null || fail '--help missing -MT'\n"
    "grep -F -- '-MQ <target>' tmp-deps-help.out >/dev/null || fail '--help missing -MQ'\n",
    "dependency help tests",
)

text = replace_once(
    text,
    "./minicc -M -MT 'build target.s' tmp-deps-main.c > tmp-deps-basic.mk\n"
    "first=$(head -n 1 tmp-deps-basic.mk)\n"
    "case \"$first\" in\n"
    "  'build\\ target.s:'*) ;;\n"
    "  *) fail \"-MT target was not Make-escaped: $first\" ;;\n"
    "esac\n",
    "./minicc -M -MQ 'build target.s' tmp-deps-main.c > tmp-deps-basic.mk\n"
    "first=$(head -n 1 tmp-deps-basic.mk)\n"
    "case \"$first\" in\n"
    "  'build\\ target.s:'*) ;;\n"
    "  *) fail \"-MQ target was not Make-escaped: $first\" ;;\n"
    "esac\n",
    "basic -MQ test",
)

anchor = "! grep -F 'stddef.h' tmp-deps-basic.mk >/dev/null || fail 'builtin header became a filesystem dependency'\n"
extra = anchor + r'''

# -MT is intentionally exact while -MQ performs Make quoting. Repeated and
# mixed target options are additive and retain argv order, matching CPP.
./minicc -M -MT '$(objpfx)raw.o' -MQ 'quoted target.o' -MT plain.o tmp-deps-main.c > tmp-deps-targets.mk
target_line=$(head -n 1 tmp-deps-targets.mk)
case "$target_line" in
  '$(objpfx)raw.o quoted\ target.o plain.o:'*) ;;
  *) fail "mixed -MT/-MQ target ordering or quoting is wrong: $target_line" ;;
esac
./minicc -M '-MQattached target.o' tmp-deps-main.c > tmp-deps-mq-attached.mk
grep -F 'attached\ target.o:' tmp-deps-mq-attached.mk >/dev/null || fail 'attached -MQ form failed'

# -MP emits one empty phony rule for every unique physical header prerequisite,
# but never for the main source or compiler-provided builtin headers.
./minicc -M -MP -MF tmp-deps-phony.mk tmp-deps-main.c
grep -Fx 'tmp-deps-tree/root.h:' tmp-deps-phony.mk >/dev/null || fail '-MP root phony rule missing'
grep -Fx 'tmp-deps-tree/sub/leaf.h:' tmp-deps-phony.mk >/dev/null || fail '-MP nested phony rule missing'
grep -Fx 'tmp-deps-space\ dir/space\ header.h:' tmp-deps-phony.mk >/dev/null || fail '-MP escaped phony rule missing'
[ "$(grep -Fx -c 'tmp-deps-tree/root.h:' tmp-deps-phony.mk || true)" -eq 1 ] || fail '-MP duplicated a physical header rule'
! grep -Fx 'tmp-deps-main.c:' tmp-deps-phony.mk >/dev/null || fail '-MP emitted a phony rule for the main source'
! grep -Fx 'stddef.h:' tmp-deps-phony.mk >/dev/null || fail '-MP emitted a phony rule for a builtin header'
'''
text = replace_once(text, anchor, extra, "-MT/-MQ/-MP tests")

text = replace_once(
    text,
    "assert_reject \"'-MF' and '-MT' require '-M' or '-MD'\" ./minicc -MF tmp-deps-orphan.mk tmp-deps-main.c\n"
    "assert_reject \"'-MF' and '-MT' require '-M' or '-MD'\" ./minicc -MT orphan tmp-deps-main.c\n"
    "assert_reject \"missing argument after '-MF'\" ./minicc -M -MF\n"
    "assert_reject \"missing argument after '-MT'\" ./minicc -M -MT\n",
    "assert_reject \"'-MF', '-MP', '-MT' and '-MQ' require '-M' or '-MD'\" ./minicc -MF tmp-deps-orphan.mk tmp-deps-main.c\n"
    "assert_reject \"'-MF', '-MP', '-MT' and '-MQ' require '-M' or '-MD'\" ./minicc -MP tmp-deps-main.c\n"
    "assert_reject \"'-MF', '-MP', '-MT' and '-MQ' require '-M' or '-MD'\" ./minicc -MT orphan tmp-deps-main.c\n"
    "assert_reject \"'-MF', '-MP', '-MT' and '-MQ' require '-M' or '-MD'\" ./minicc -MQ orphan tmp-deps-main.c\n"
    "assert_reject \"missing argument after '-MF'\" ./minicc -M -MF\n"
    "assert_reject \"missing argument after '-MT'\" ./minicc -M -MT\n"
    "assert_reject \"missing argument after '-MQ'\" ./minicc -M -MQ\n",
    "dependency option diagnostics",
)

test.write_text(text)
