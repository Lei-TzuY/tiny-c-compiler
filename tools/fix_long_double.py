from pathlib import Path
p=Path('codegen.c')
s=p.read_text()
old='''    if (node->ty->kind == TY_LDOUBLE) {
        gen_addr(node->lhs);
        push();
        load(node->ty);
        if (return_old) {
            printf("  sub $16, %%rsp\\n");
            printf("  fld %%st(0)\\n");
            printf("  fstpt (%%rsp)\\n");
            depth += 2;
        }
        printf("  fld1\\n");
        printf(increment ? "  faddp %%st, %%st(1)\\n"
                         : "  fsubrp %%st, %%st(1)\\n");
        store(node->ty);
        if (return_old) {
            printf("  fstp %%st(0)\\n");
            printf("  fldt (%%rsp)\\n");
            printf("  add $16, %%rsp\\n");
            depth -= 2;
        }
        return;
    }
'''
new='''    if (node->ty->kind == TY_LDOUBLE) {
        gen_addr(node->lhs);
        push();
        load(node->ty);
        // Keep the post-inc/dec old value below the working value on the x87
        // register stack. This avoids interposing scratch bytes above the saved
        // lvalue address that store() pops from the machine stack.
        if (return_old)
            printf("  fld %%st(0)\\n");
        printf("  fld1\\n");
        printf(increment ? "  faddp %%st, %%st(1)\\n"
                         : "  fsubrp %%st, %%st(1)\\n");
        store(node->ty);
        if (return_old)
            printf("  fstp %%st(0)\\n");
        return;
    }
'''
if s.count(old)!=1:
    raise SystemExit(f'expected long-double inc/dec block once, got {s.count(old)}')
p.write_text(s.replace(old,new))
