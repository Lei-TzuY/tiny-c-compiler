from pathlib import Path
p=Path('codegen.c')
s=p.read_text()
old='''        printf("  pop %%rbp\\n");\n        printf("  ret\\n");\n    }\n}\n'''
new='''        printf("  pop %%rbp\\n");\n        printf("  ret\\n");\n    }\n\n    // GNU/ELF linkers treat an input object without this marker as potentially\n    // requiring an executable stack. Generated C code never needs one, so emit\n    // the conventional empty note section explicitly.\n    printf("  .section .note.GNU-stack,\\\"\\\",@progbits\\n");\n}\n'''
if s.count(old)!=1:
    raise SystemExit(f'codegen epilogue anchor count={s.count(old)}')
p.write_text(s.replace(old,new,1))
