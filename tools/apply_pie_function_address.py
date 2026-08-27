from pathlib import Path

p = Path('codegen.c')
s = p.read_text()
old = '''    if (node->kind == ND_VAR) {\n        if (node->var->is_local)\n            printf("  lea %d(%%rbp), %%rax\\n", node->var->offset);\n        else\n            printf("  lea %s(%%rip), %%rax\\n", node->var->name);\n        return;\n    }\n'''
new = '''    if (node->kind == ND_VAR) {\n        if (node->var->is_local)\n            printf("  lea %d(%%rbp), %%rax\\n", node->var->offset);\n        else if (node->var->is_function && !node->var->is_static)\n            // A default-visible function may be interposed, so materialize its\n            // address through the GOT. This is valid in PIE code and also works\n            // for functions defined in the current translation unit.\n            printf("  mov %s@GOTPCREL(%%rip), %%rax\\n", node->var->name);\n        else\n            printf("  lea %s(%%rip), %%rax\\n", node->var->name);\n        return;\n    }\n'''
if old not in s:
    raise SystemExit('gen_addr variable block not found')
s = s.replace(old, new, 1)
p.write_text(s)
print('PIE-safe function address migration applied')
