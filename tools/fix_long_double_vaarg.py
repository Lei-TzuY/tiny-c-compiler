from pathlib import Path

p = Path('parse.c')
s = p.read_text()
old = '''        bool gp = ty->kind == TY_PTR || (is_integer(ty) && ty->size >= 4);
        bool fp = ty->kind == TY_DOUBLE;
        bool record = ty->kind == TY_STRUCT && supported_record_abi(ty);
        if (!gp && !fp && !record)
            error_at(builtin->loc, "unsupported or unpromoted type in va_arg");
'''
new = '''        bool gp = ty->kind == TY_PTR || (is_integer(ty) && ty->size >= 4);
        bool fp = ty->kind == TY_DOUBLE || ty->kind == TY_LDOUBLE;
        bool record = ty->kind == TY_STRUCT && supported_record_abi(ty);
        if (!gp && !fp && !record)
            error_at(builtin->loc, "unsupported or unpromoted type in va_arg");
'''
if s.count(old) != 1:
    raise SystemExit(f'expected va_arg scalar-class block once, got {s.count(old)}')
p.write_text(s.replace(old, new))
