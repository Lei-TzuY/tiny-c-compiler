from pathlib import Path

p = Path('preprocess_v2.c')
s = p.read_text()
old = '''        return "typedef void *va_list;\\n"\n               "#define va_start(ap, last) ((ap) = (void*)&(last) + 8)\\n"\n               "#define va_arg(ap, type) (*(type*)((ap) += 8, (ap) - 8))\\n"\n               "#define va_end(ap) ((void)0)\\n";\n'''
new = '''        return "typedef char *va_list;\\n"\n               "#define va_start(ap, last) ((ap) = (char*)&(last) + 8)\\n"\n               "#define va_arg(ap, type) (*(type*)((ap) += 8, (ap) - 8))\\n"\n               "#define va_end(ap) ((void)0)\\n";\n'''
if s.count(old) != 1:
    raise SystemExit(f'stdarg builtin anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))
