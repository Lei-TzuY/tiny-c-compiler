#ifndef MINICC_H
#define MINICC_H

#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <ctype.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

char *strndup(const char *s, size_t n);

//
// preprocess.c
//
char *preprocess(char *input);

//
// tokenize.c
//

typedef struct Type Type;
typedef struct Node Node;
typedef struct Obj Obj;
typedef struct Member Member;

typedef enum {
    TK_IDENT,   // Identifiers
    TK_PUNCT,   // Punctuators
    TK_KEYWORD, // Keywords
    TK_STR,     // String literals
    TK_NUM,     // Numeric literals (int or float)
    TK_EOF,     // End-of-file markers
} TokenKind;

typedef struct Token Token;
struct Token {
    TokenKind kind; // Token kind
    Token *next;    // Next token
    int64_t val;    // If kind is TK_NUM (integer), its value
    double fval;    // If kind is TK_NUM (floating point), its value
    bool is_float;  // True if token is a floating point constant
    char *loc;      // Token location
    int len;        // Token length
    Type *ty;       // Used if TK_STR or TK_NUM
    char *str;      // String literal contents including terminating '\0'
    int line_no;    // Line number (1-based)
};

_Noreturn void error(char *fmt, ...);
_Noreturn void error_at(char *loc, char *fmt, ...);
bool equal(Token *tok, char *op);
Token *skip(Token *tok, char *op);
bool consume(Token **rest, Token *tok, char *str);
Token *tokenize(char *input);

//
// parse.c
//

typedef enum {
    TY_INT,
    TY_LONG,
    TY_LLONG,
    TY_CHAR,
    TY_SHORT,
    TY_PTR,
    TY_ARRAY,
    TY_VOID,
    TY_STRUCT,
    TY_BOOL,
    TY_FUNC,
    TY_FLOAT,
    TY_DOUBLE,
} TypeKind;

struct Type {
    TypeKind kind;
    int size;         // sizeof() value
    int align;        // alignment requirement
    bool is_unsigned; // true for unsigned integer types
    bool is_plain_char; // distinguish plain char from signed/unsigned char
    bool is_incomplete; // forward-declared struct/union with no body yet
    bool is_union;      // TY_STRUCT represents both records; true for union
    bool has_flexible_array_member; // complete struct itself ends in a flexible array member
    bool contains_flexible_array_member; // direct-FAM struct or union recursively containing one
    Type *base;       // Pointer or array
    int array_len;    // Array
    // Parameter-array qualifiers written inside the outermost [] apply
    // to the pointer produced by C's array-parameter adjustment. These
    // fields exist only until func_params() performs that adjustment.
    bool param_array_const;
    bool param_array_volatile;
    bool param_array_restrict;
    Member *members;  // Struct members
    Type *return_ty;  // TY_FUNC: return type
    Obj *params;       // TY_FUNC: declared parameter types (metadata Obj list)
    bool is_variadic; // TY_FUNC: variadic function (...)
    bool has_prototype; // TY_FUNC: distinguish f(void)/f(int) from old-style f()

    // C type qualifiers. Qualified types are shallow clones; origin preserves
    // record identity and qual_next keeps incomplete tagged-record clones in
    // sync when the canonical tag is completed later.
    bool is_const;
    bool is_volatile;
    bool is_restrict;
    Type *origin;
    Type *qual_next;
};

struct Member {
    Member *next;
    char *name;
    Type *ty;
    bool is_anonymous; // unnamed C11 struct/union member; nested names are promoted
    int align;      // explicit _Alignas requirement, 0 = natural type alignment
    int offset;
};

extern Type *ty_int;
extern Type *ty_long;
extern Type *ty_llong;
extern Type *ty_char;
extern Type *ty_schar;
extern Type *ty_short;
extern Type *ty_void;
extern Type *ty_bool;
extern Type *ty_uint;
extern Type *ty_ulong;
extern Type *ty_ullong;
extern Type *ty_uchar;
extern Type *ty_ushort;
extern Type *ty_float;
extern Type *ty_double;

bool is_integer(Type *ty);
bool is_flonum(Type *ty);
bool is_numeric(Type *ty);
Type *default_argument_promotion(Type *ty);
bool prototype_compatible_with_unprototyped(Type *fty);

typedef enum {
    SYSV_ABI_NONE,
    SYSV_ABI_INTEGER,
    SYSV_ABI_SSE,
} SysVAbiClass;

int sysv_classify_record(Type *ty, SysVAbiClass classes[2]);
bool sysv_record_is_memory(Type *ty);
Type *pointer_to(Type *base);
Type *array_of(Type *base, int size);
Type *func_type(Type *return_ty);
Type *qualify_type(Type *ty, bool is_const, bool is_volatile, bool is_restrict);
Type *get_common_type(Type *ty1, Type *ty2);
int64_t eval_const_expr(Node *node);
bool is_null_pointer_constant(Node *node);
void add_type(Node *node);

typedef enum {
    ND_ADD,       // +
    ND_SUB,       // -
    ND_MUL,       // *
    ND_DIV,       // /
    ND_POS,       // unary +
    ND_NEG,       // unary -
    ND_EQ,        // ==
    ND_NE,        // !=
    ND_LT,        // <
    ND_LE,        // <=
    ND_LOGAND,    // &&
    ND_LOGOR,     // ||
    ND_NOT,       // !
    ND_ASSIGN,    // =
    ND_ADD_EQ,    // +=
    ND_SUB_EQ,    // -=
    ND_MUL_EQ,    // *=
    ND_DIV_EQ,    // /=
    ND_PRE_INC,   // prefix ++
    ND_PRE_DEC,   // prefix --
    ND_POST_INC,  // postfix ++
    ND_POST_DEC,  // postfix --
    ND_RETURN,    // "return"
    ND_IF,        // "if"
    ND_WHILE,     // "while"
    ND_FOR,       // "for"
    ND_BLOCK,     // { ... }
    ND_FUNCALL,   // Function call
    ND_VA_START,  // compiler-backed va_start
    ND_VA_ARG,    // compiler-backed typed va_arg
    ND_ADDR,      // & (address-of)
    ND_DEREF,     // * (dereference)
    ND_EXPR_STMT, // Expression statement
    ND_VAR,       // Variable
    ND_NUM,       // Integer or Float constant
    ND_MOD,       // %
    ND_BITNOT,    // ~
    ND_BITAND,    // &
    ND_BITOR,     // |
    ND_BITXOR,    // ^
    ND_SHL,       // <<
    ND_SHR,       // >>
    ND_MOD_EQ,    // %=
    ND_AND_EQ,    // &=
    ND_OR_EQ,     // |=
    ND_XOR_EQ,    // ^=
    ND_SHL_EQ,    // <<=
    ND_SHR_EQ,    // >>=
    ND_TERNARY,   // ?:
    ND_CAST,      // (type)expr
    ND_BREAK,     // "break"
    ND_CONTINUE,  // "continue"
    ND_DO,        // "do"
    ND_SWITCH,    // "switch"
    ND_CASE,      // "case"
    ND_DEFAULT,   // "default"
    ND_MEMBER,    // struct member (. and ->)
    ND_COMMA,     // , (comma operator)
    ND_COMPOUND_LITERAL, // (type-name){ initializer-list }
    ND_GOTO,      // "goto"
    ND_LABEL,     // labeled statement
} NodeKind;

struct Node {
    NodeKind kind; // Node kind
    Node *next;    // Next node

    Node *lhs;     // Left-hand side
    Node *rhs;     // Right-hand side

    // "if", "while" or "for" statement
    Node *cond;
    Node *then;
    Node *els;
    Node *init;
    Node *inc;

    Node *body;    // Block or function body

    char *funcname; // Function call name (NULL for indirect calls)
    Node *args;     // Function arguments
    
    char *name;    // Variable name (also used for some generic names)
    Obj *var;      // Variable reference
    Type *ty;      // Type of this node
    Member *member; // Used if kind == ND_MEMBER
    Obj *ret_buffer; // Hidden local materialization for by-value record calls

    int64_t val;   // Used if kind == ND_NUM (integer)
    double fval;   // Used if kind == ND_NUM (float)

    // goto / label
    char *label_name;    // goto target or label name (source)
    char *unique_label;  // unique assembly label generated for codegen
    Node *goto_next;     // linked list of gotos in a function
    Node *label_next;    // linked list of labels in a function
};

typedef struct Relocation Relocation;
struct Relocation {
    Relocation *next;
    int offset;
    char *label;
    int64_t addend;
};

struct Obj {
    Obj *next;
    Obj *param_next;
    char *name;    // Variable name
    Type *ty;      // Variable type
    int align;     // explicit _Alignas requirement, 0 = natural type alignment
    bool is_local; // local or global/constant

    // Local variable
    int offset;    // Offset from RBP

    // Global variable or string literal
    char *init_data;
    bool is_string_literal; // compiler-generated literal storage belongs in .rodata
    int64_t init_val;    // for initialized global scalars
    double finit_val;    // for initialized double/float global scalars
    bool has_init_val;
    char *init_reloc_label;   // static address constant relocation target
    int64_t init_reloc_addend; // byte addend applied to relocation target
    bool has_init_reloc;

    // Typed aggregate static initializer. The image is zero-filled and stores
    // all ordinary bytes/padding; relocations replace pointer-sized ranges.
    char *init_image;
    int init_image_size;
    Relocation *init_relocs;

    // Legacy homogeneous aggregate storage retained for compatibility.
    // Global array/struct initializer (list of int64/double values, one per element)
    int64_t *init_vals;
    double *finit_vals;
    int init_vals_count;

    // Flags
    bool is_function;  // true = function symbol (not a variable)
    bool is_static;    // static storage class
    bool is_extern;    // extern storage class
    bool is_register;  // register storage class; address may not be taken
    bool is_thread_local; // C11 _Thread_local storage duration
    bool is_defined;   // function symbol already has a body
};

typedef struct Function Function;
struct Function {
    Function *next;
    char *name;
    Obj *params;   // Parameters
    Type *return_ty; // Function return type
    Node *body;
    Obj *locals;   // Local variables
    int stack_size;
    int sret_offset;    // saved hidden SysV MEMORY-return pointer, relative to RBP
    bool is_static;
    bool is_variadic;
    int va_offset;       // SysV register-save area base, relative to RBP
    int va_gp_offset;    // initial gp_offset for va_start
    int va_fp_offset;    // initial fp_offset for va_start
    int va_stack_offset; // first unnamed stack arg, relative to RBP
    Node *gotos;   // linked list of goto nodes
    Node *labels;  // linked list of label nodes
};

// Program
typedef struct Program Program;
struct Program {
    Obj *globals;
    Function *fns;
};

Program *parse(Token *tok);

//
// codegen.c
//

void codegen(Program *prog);

#endif
