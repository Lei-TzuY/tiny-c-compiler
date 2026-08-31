from pathlib import Path

p = Path('parse.c')
s = p.read_text()
old = '''                if (!assoc_ty || assoc_ty->kind == TY_VOID || assoc_ty->kind == TY_FUNC ||
                    assoc_ty->is_incomplete ||
                    (assoc_ty->kind == TY_ARRAY && assoc_ty->array_len == 0))
                    error_at(type_tok->loc,
                             "generic association requires a complete object type");
'''
new = '''                if (!assoc_ty || assoc_ty->kind == TY_VOID || assoc_ty->kind == TY_FUNC ||
                    assoc_ty->is_incomplete ||
                    (assoc_ty->kind == TY_ARRAY && assoc_ty->array_len == 0))
                    error_at(type_tok->loc,
                             "generic association requires a complete object type");
                if (type_is_variably_modified(assoc_ty))
                    error_at(type_tok->loc,
                             "generic association type must not be variably modified");
'''
if old not in s:
    raise SystemExit('parse.c target not found')
p.write_text(s.replace(old, new, 1))

p = Path('test/generic_selection.sh')
s = p.read_text()
marker = '''reject missing-association <<'EOF'
int main(void){return _Generic(1, );}
EOF
'''
addition = '''reject variably-modified-vla-association <<'EOF'
int main(void){
  int n=3;
  return _Generic(1, int[n]:1, default:0);
}
EOF

reject variably-modified-pointer-association <<'EOF'
int main(void){
  int n=3;
  return _Generic(1, int (*)[n]:1, default:0);
}
EOF

'''
if marker not in s:
    raise SystemExit('generic_selection.sh target not found')
p.write_text(s.replace(marker, addition + marker, 1))
