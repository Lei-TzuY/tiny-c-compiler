from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"missing anchor for {label} in {path}")
    p.write_text(s.replace(old, new, 1))


replace_once(
    "parse.c",
    '''    if (equal(tok, "(")) {
        Token *start = tok;
        Type dummy = {};
        declarator_impl(&tok, start->next, &dummy, ident, allow_abstract,
                        parameter_declarator);
        tok = skip(tok, ")");
        // A suffix outside a parenthesized declarator is not the direct
        // outermost array derivation of the parameter identifier. Parameter
        // array qualifiers/static are therefore forbidden at this level.
        ty = type_suffix(rest, tok, ty, false);
        return declarator_impl(&tok, start->next, ty, ident, allow_abstract,
                               parameter_declarator);
    }
''',
    '''    if (equal(tok, "(")) {
        Token *start = tok;
        Type dummy = {};
        Type *shape = declarator_impl(&tok, start->next, &dummy, ident,
                                      allow_abstract, parameter_declarator);
        tok = skip(tok, ")");

        // Redundant grouping around the identifier does not stop a following
        // array suffix from being the parameter's outermost array derivation:
        // `int (a)[const 3]` adjusts just like `int a[const 3]`. If the grouped
        // declarator introduced any real derived type (`(*a)`, `(a[2])`, ...),
        // the following array is nested and may not carry parameter-only syntax.
        bool direct_parameter_array = parameter_declarator && shape == &dummy;
        ty = type_suffix(rest, tok, ty, direct_parameter_array);
        return declarator_impl(&tok, start->next, ty, ident, allow_abstract,
                               parameter_declarator);
    }
''',
    "shape-aware grouped parameter array",
)

p = Path("test/parameter_array_qualifiers.sh")
s = p.read_text()
anchor = "assert_run 19 'int f(int *a[static 2]){return *a[1];} int main(void){int x=0,y=19;int *a[2]={&x,&y};return f(a);}'\n"
extra = """assert_run 20 'int f(int (a)[const 3]){return a[0];} int main(void){int a[3]={20};return f(a);}'
assert_run 21 'int f(int ((a))[restrict static 3]){return a[0];} int main(void){int a[3]={21};return f(a);}'
"""
if anchor not in s:
    raise SystemExit("grouped positive test anchor missing")
s = s.replace(anchor, anchor + extra, 1)

anchor2 = "assert_reject 'int f(int (*a)[static 3]){return 0;} int main(void){return 0;}'\n"
extra2 = "assert_reject 'int f(int (*a)[const 3]){return 0;} int main(void){return 0;}'\n"
if anchor2 not in s:
    raise SystemExit("grouped negative test anchor missing")
s = s.replace(anchor2, anchor2 + extra2, 1)
p.write_text(s)
