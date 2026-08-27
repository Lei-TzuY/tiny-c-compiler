from pathlib import Path

parse = Path("parse.c")
s = parse.read_text()

old_local = '''    if (equal(tok, "typedef")) {
        tok = tok->next;
        Type *basety = declspec(&tok, tok);
        if (!equal(tok, ";")) {
            Token *ident;
            basety = declarator(&tok, tok, basety, &ident);
            TypeDef *td = calloc(1, sizeof(TypeDef));
            td->name = strndup(ident->loc, ident->len);
            td->ty = basety;
            td->next = typedefs; typedefs = td;
        }
        *rest = skip(tok, ";");
        return new_node(ND_EXPR_STMT);
    }
'''
new_local = '''    if (equal(tok, "typedef")) {
        tok = tok->next;
        Type *basety = declspec(&tok, tok);
        if (!equal(tok, ";")) {
            for (;;) {
                Token *ident;
                Type *ty = declarator(&tok, tok, basety, &ident);
                TypeDef *td = calloc(1, sizeof(TypeDef));
                td->name = strndup(ident->loc, ident->len);
                td->ty = ty;
                td->next = typedefs;
                typedefs = td;
                if (!consume(&tok, tok, ","))
                    break;
            }
        }
        *rest = skip(tok, ";");
        return new_node(ND_EXPR_STMT);
    }
'''

old_top = '''        if (equal(tok, "typedef")) {
            tok = tok->next;
            Type *basety = declspec(&tok, tok);
            if (!equal(tok, ";")) {
                Token *ident;
                basety = declarator(&tok, tok, basety, &ident);
                TypeDef *td = calloc(1, sizeof(TypeDef));
                td->name = strndup(ident->loc, ident->len);
                td->ty = basety;
                td->next = typedefs; typedefs = td;
            }
            tok = skip(tok, ";");
            continue;
        }
'''
new_top = '''        if (equal(tok, "typedef")) {
            tok = tok->next;
            Type *basety = declspec(&tok, tok);
            if (!equal(tok, ";")) {
                for (;;) {
                    Token *ident;
                    Type *ty = declarator(&tok, tok, basety, &ident);
                    TypeDef *td = calloc(1, sizeof(TypeDef));
                    td->name = strndup(ident->loc, ident->len);
                    td->ty = ty;
                    td->next = typedefs;
                    typedefs = td;
                    if (!consume(&tok, tok, ","))
                        break;
                }
            }
            tok = skip(tok, ";");
            continue;
        }
'''

old_global = '''        } else {
            if (!is_extern && is_incomplete_object_type(ty))
                error_at(ident->loc, "variable has incomplete type");

            // Global variable(s) (possibly with initializer)
            for (;;) {
                Obj *var = calloc(1, sizeof(Obj));
'''
new_global = '''        } else {
            // Global variable(s) (possibly with initializer)
            for (;;) {
                if (!is_extern && is_incomplete_object_type(ty))
                    error_at(ident->loc, "variable has incomplete type");

                Obj *var = calloc(1, sizeof(Obj));
'''

for old, new, label in [
    (old_local, new_local, "local typedef list"),
    (old_top, new_top, "top-level typedef list"),
    (old_global, new_global, "global incomplete declarator check"),
]:
    if old not in s:
        raise SystemExit(f"expected parser block not found: {label}")
    s = s.replace(old, new, 1)

parse.write_text(s)

path = Path("test/incomplete_tags.sh")
t = path.read_text()
marker = 'echo "All incomplete record/tag scope tests passed!"\n'
if marker not in t:
    raise SystemExit("test marker not found")
extra = '''\n# Every declarator in a comma-separated declaration must be validated independently.\nassert_reject 'struct S; struct S *ptr, value; int main() { return 0; }'\nassert_reject 'struct S; static struct S *ptr, value; int main() { return 0; }'\nassert_record 6 'struct S; extern struct S *ptr, value; struct S { int x; }; int main() { struct S s; s.x=6; return s.x; }'\n\n# typedef declarations may introduce more than one name.\nassert_record 11 'typedef int A, B; int main() { A a=5; B b=6; return a+b; }'\nassert_record 8 'typedef struct Pair Pair, *PairPtr; struct Pair { int x; }; int main() { Pair p; PairPtr q=&p; q->x=8; return p.x; }'\nassert_record 9 'int main() { typedef int A, B; A a=4; B b=5; return a+b; }'\n\n'''
t = t.replace(marker, extra + marker, 1)
path.write_text(t)

print("declarator-list migration applied")
