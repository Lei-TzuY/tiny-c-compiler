from pathlib import Path

pp = Path('preprocess_v2.c')
text = pp.read_text()
old = '''            } else if (is_cond_active() && !strcmp(directive, "include")) {
                char quote = *start;
                if (quote == '\"' || quote == '<') {
                    char end_quote = quote == '\"' ? '\"' : '>';
                    char *hname = start + 1;
                    char *end_h = strchr(hname, end_quote);
                    if (!end_h)
                        error("unterminated #include");
                    *end_h = '\\0';
                    char *owned = NULL;
                    const char *content = NULL;
                    if (quote == '\"')
                        owned = read_file_content(hname);
                    content = owned ? owned : get_builtin_header(hname);
                    if (!content)
                        error("cannot include %s", hname);
                    char *sub = preprocess_v2_source((char *)content, hname);
                    sb_puts(&out, sub);
                    if (out.len && out.data[out.len - 1] != '\\n')
                        sb_putc(&out, '\\n');
                    free(sub);
                    free(owned);
                }
'''
new = '''            } else if (is_cond_active() && !strcmp(directive, "include")) {
                // C11 6.10.2: if the directive does not directly contain a
                // header-name token, macro-expand the remaining preprocessing
                // tokens and interpret the result as the header name.
                char *expanded_include = NULL;
                char *include_operand = start;
                if (*include_operand != '\"' && *include_operand != '<') {
                    bool directive_comment = false;
                    expanded_include = expand_text(include_operand, NULL, &directive_comment);
                    include_operand = expanded_include;
                    while (*include_operand == ' ' || *include_operand == '\\t')
                        include_operand++;
                }

                char quote = *include_operand;
                if (quote != '\"' && quote != '<')
                    error("#include requires a header name");
                char end_quote = quote == '\"' ? '\"' : '>';
                char *hname = include_operand + 1;
                char *end_h = strchr(hname, end_quote);
                if (!end_h)
                    error("unterminated #include");
                *end_h = '\\0';

                char *owned = NULL;
                const char *content = NULL;
                if (quote == '\"')
                    owned = read_file_content(hname);
                content = owned ? owned : get_builtin_header(hname);
                if (!content)
                    error("cannot include %s", hname);
                char *sub = preprocess_v2_source((char *)content, hname);
                sb_puts(&out, sub);
                if (out.len && out.data[out.len - 1] != '\\n')
                    sb_putc(&out, '\\n');
                free(sub);
                free(owned);
                free(expanded_include);
'''
if old not in text:
    raise SystemExit('preprocess include block not found')
pp.write_text(text.replace(old, new, 1))


test = Path('test/preprocessor.sh')
t = test.read_text()
needle = '''# Built-in header macros still work with recursive expansion enabled.\nassert_pp 1 '#include <stdbool.h>\nint main() { bool value = true; return value; }'\n\necho "All preprocessor tests passed!"\n'''
replacement = '''# Built-in header macros still work with recursive expansion enabled.\nassert_pp 1 '#include <stdbool.h>\nint main() { bool value = true; return value; }'\n\n# C11 #include operands that are not direct header-name tokens are macro-expanded.\nassert_pp 1 '#define BOOL_HEADER <stdbool.h>\n#include BOOL_HEADER\nint main() { bool value = true; return value; }'\n\nassert_pp 1 '#define HEADER_NAME stdbool.h\n#define WRAP_HEADER(x) <x>\n#include WRAP_HEADER(HEADER_NAME)\nint main() { bool value = true; return value; }'\n\nprintf '%s\\n' 'int included_value(void) { return 23; }' > tmp-macro-include.h\nassert_pp 23 '#define LOCAL_HEADER "tmp-macro-include.h"\n#include LOCAL_HEADER\nint main() { return included_value(); }'\nrm -f tmp-macro-include.h\n\necho "All preprocessor tests passed!"\n'''
if needle not in t:
    raise SystemExit('preprocessor test insertion point not found')
test.write_text(t.replace(needle, replacement, 1))

readme = Path('README.md')
r = readme.read_text()
old_r = '- **Preprocessor**: object-like and function-like macros, recursive expansion, `#include`, `#define`, `#undef`, `#if/#elif/#else/#endif`, `#ifdef/#ifndef`, `defined`, variadic macros with `__VA_ARGS__`, stringification `#`, token pasting `##`, source line splicing, and `#error`'
new_r = '- **Preprocessor**: object-like and function-like macros, recursive expansion, direct and macro-expanded `#include`, `#define`, `#undef`, `#if/#elif/#else/#endif`, `#ifdef/#ifndef`, `defined`, variadic macros with `__VA_ARGS__`, stringification `#`, token pasting `##`, source line splicing, and `#error`'
if old_r not in r:
    raise SystemExit('README preprocessor feature line not found')
readme.write_text(r.replace(old_r, new_r, 1))
