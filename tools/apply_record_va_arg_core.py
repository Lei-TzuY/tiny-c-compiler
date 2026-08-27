from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "parse.c",
    '''        // This scalar SysV subset supports the promoted variadic types that
        // occupy one GP slot or one SSE double slot. Asking for float or a
        // narrow integer after default argument promotions is a C misuse.
        bool gp = ty->kind == TY_PTR || (is_integer(ty) && ty->size >= 4);
        bool fp = ty->kind == TY_DOUBLE;
        if (!gp && !fp)
            error_at(builtin->loc, "unsupported or unpromoted type in va_arg");

        Node *node = new_unary(ND_VA_ARG, ap);
        node->ty = ty;
        *rest = tok;
        return node;
''',
    '''        // Default-promoted scalar types continue to use one GP/SSE slot.
        // Records use the same INTEGER/SSE/MEMORY classifier as ordinary calls
        // and are materialized into an anonymous local result object.
        bool gp = ty->kind == TY_PTR || (is_integer(ty) && ty->size >= 4);
        bool fp = ty->kind == TY_DOUBLE;
        bool record = ty->kind == TY_STRUCT && supported_record_abi(ty);
        if (!gp && !fp && !record)
            error_at(builtin->loc, "unsupported or unpromoted type in va_arg");

        Node *node = new_unary(ND_VA_ARG, ap);
        node->ty = ty;
        if (record) {
            Obj *buf = create_lvar(new_unique_name());
            buf->ty = ty;
            node->ret_buffer = buf;
        }
        *rest = tok;
        return node;
''',
)

p = Path("codegen.c")
text = p.read_text()
anchor = "static void gen_expr(Node *node) {\n"
helper = r'''// Copy one low eightbyte from the variadic register-save area into a
// record result local. Only bytes belonging to the C object are stored.
static void copy_va_register_slot_to_local(const char *index_reg,
                                           int dst, int bytes) {
    printf("  mov (%%rdx,%s), %%r10\n", index_reg);
    store_register_bytes_to_local("%r10", dst, bytes);
}

static void copy_va_stack_record_to_local(Type *ty, int dst) {
    int slots = (ty->size + 7) / 8;
    for (int i = 0; i < slots; i++) {
        int bytes = ty->size - i * 8;
        if (bytes > 8)
            bytes = 8;
        printf("  mov %d(%%rdx), %%r10\n", i * 8);
        store_register_bytes_to_local("%r10", dst + i * 8, bytes);
    }
}

// Aggregate va_arg mirrors the ordinary SysV classifier. Small records consume
// independent GP/SSE save slots only when every required class is available;
// otherwise the whole value comes from overflow_arg_area. MEMORY records always
// come from overflow_arg_area and do not consume either register cursor.
static void gen_record_va_arg(Node *node) {
    RecordAbi abi = require_record_abi(node->ty);
    if (!node->ret_buffer)
        error("missing record va_arg materialization buffer");

    gen_expr(node->lhs);
    printf("  mov %%rax, %%rdi\n");
    int c = count();

    if (!abi.memory) {
        if (abi.gp) {
            printf("  mov 0(%%rdi), %%eax\n");
            printf("  cmp $%d, %%eax\n", 48 - abi.gp * 8);
            printf("  ja .L.va_record_stack.%d\n", c);
        }
        if (abi.fp) {
            printf("  mov 4(%%rdi), %%eax\n");
            printf("  cmp $%d, %%eax\n", 176 - abi.fp * 16);
            printf("  ja .L.va_record_stack.%d\n", c);
        }

        printf("  mov 0(%%rdi), %%esi\n");
        printf("  mov 4(%%rdi), %%ecx\n");
        printf("  mov 16(%%rdi), %%rdx\n");
        for (int i = 0; i < abi.slots; i++) {
            int bytes = node->ty->size - i * 8;
            if (bytes > 8)
                bytes = 8;
            if (abi.classes[i] == SYSV_ABI_INTEGER) {
                copy_va_register_slot_to_local("%rsi", node->ret_buffer->offset + i * 8, bytes);
                printf("  add $8, %%esi\n");
            } else if (abi.classes[i] == SYSV_ABI_SSE) {
                copy_va_register_slot_to_local("%rcx", node->ret_buffer->offset + i * 8, bytes);
                printf("  add $16, %%ecx\n");
            } else {
                error("invalid SysV record class in va_arg");
            }
        }
        if (abi.gp)
            printf("  mov %%esi, 0(%%rdi)\n");
        if (abi.fp)
            printf("  mov %%ecx, 4(%%rdi)\n");
        printf("  lea %d(%%rbp), %%rax\n", node->ret_buffer->offset);
        printf("  jmp .L.va_record_end.%d\n", c);
    }

    printf(".L.va_record_stack.%d:\n", c);
    printf("  mov 8(%%rdi), %%rdx\n");
    if (node->ty->align > 8) {
        printf("  add $%d, %%rdx\n", node->ty->align - 1);
        printf("  and $-%d, %%rdx\n", node->ty->align);
    }
    copy_va_stack_record_to_local(node->ty, node->ret_buffer->offset);
    printf("  add $%d, %%rdx\n", abi.slots * 8);
    printf("  mov %%rdx, 8(%%rdi)\n");
    printf("  lea %d(%%rbp), %%rax\n", node->ret_buffer->offset);
    printf(".L.va_record_end.%d:\n", c);
}

'''
if anchor not in text:
    raise SystemExit("gen_expr anchor not found")
p.write_text(text.replace(anchor, helper + anchor, 1))

replace_once(
    "codegen.c",
    '''    if (node->kind == ND_VA_ARG) {
        gen_expr(node->lhs); // RAX = &va_list
''',
    '''    if (node->kind == ND_VA_ARG) {
        if (node->ty->kind == TY_STRUCT) {
            gen_record_va_arg(node);
            return;
        }

        gen_expr(node->lhs); // RAX = &va_list
''',
)
