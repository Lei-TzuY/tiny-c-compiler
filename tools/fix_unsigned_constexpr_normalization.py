from pathlib import Path

p = Path('parse.c')
s = p.read_text()
old = '''    if (ty->size == 1)\n        return ty->is_unsigned ? (uint8_t)val : (int8_t)val;\n    if (ty->size == 2)\n        return ty->is_unsigned ? (uint16_t)val : (int16_t)val;\n    if (ty->size == 4)\n        return ty->is_unsigned ? (uint32_t)val : (int32_t)val;\n    return val;\n'''
new = '''    if (ty->size == 1) {\n        if (ty->is_unsigned) return (uint8_t)val;\n        return (int8_t)val;\n    }\n    if (ty->size == 2) {\n        if (ty->is_unsigned) return (uint16_t)val;\n        return (int16_t)val;\n    }\n    if (ty->size == 4) {\n        if (ty->is_unsigned) return (uint32_t)val;\n        return (int32_t)val;\n    }\n    return val;\n'''
if s.count(old) != 1:
    raise SystemExit(f'parse.c: signed-normalization anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))
