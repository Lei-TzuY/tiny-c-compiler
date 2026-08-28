# Mini C Compiler

An educational C compiler implemented in C. The pipeline includes preprocessing, tokenization, parsing, type analysis, and x86-64 code generation; the shell test suite documents and exercises the supported language subset.

## Supported Language Features

- **Types**: `char`/`signed char`/`unsigned char` as distinct 1B types, `short` (2B), `int` (4B), `long`/`long long` (8B with distinct C ranks), `float` (4B), `double` (8B), `void`, pointers, arrays, `struct`, `union`, tagged `enum`, `typedef`, `signed`/`unsigned` integer type specifiers, typed integer literal suffixes (`U`, `L`, `UL`, `LL`, `ULL`), semantic `const`/`volatile`/`restrict` qualifiers (including pointer qualifiers and qualifier-safe pointer conversions); enumerators accept integer constant expressions whose values are representable as `int`
- **Operators**: arithmetic, bitwise, logical, comparison, ternary `?:`, comma `,`, `sizeof`, C11 `_Alignof(type-name)` and `_Generic` selection with ordinary controlling-expression value conversions, prefix/postfix `++/--`, all compound assignments (`+= -= *= /= %= &= |= ^= <<= >>=`), type cast; `sizeof` and `_Alignof` produce the LP64 `size_t` type (`unsigned long`); pointer arithmetic follows complete-object rules with array decay, element-size scaling, compatible pointer subtraction, and rejection of `void *`/function-pointer arithmetic; integer promotions and LP64 usual arithmetic conversions drive mixed signed/unsigned arithmetic, comparison, shifts, and compound division/remainder/right-shift code generation
- **Control flow**: `if/else`, `while`, `for` (including init declarations), `do-while`, `switch/case/default` with integer controlling expressions, integer-constant-expression cases, promoted case-value normalization, duplicate case/default diagnostics, and case/default labeled statements nested inside blocks/conditionals/loops, `break`, `continue`, `return`, `goto`/labels
- **Declarations**: validated C type-specifier sets (including required explicit type specifiers, order-independent signed/unsigned integer forms, and explicit rejection of unsupported `long double`), rejection of direct `void` objects and void/function-typed record members, rejection of block-scope `extern` initializers, order-independent `typedef` storage-class declarations, block-scope `auto`/`register` objects with single-storage-class constraint checking and C address-taking restrictions for register objects/parameters, C11 `_Noreturn` function declarations (including `<stdnoreturn.h>` `noreturn`), recursive C declarators with pointer/array/function grouping (including arrays of function pointers and functions returning function pointers), recursive abstract type names shared by casts and `sizeof(type-name)`, compatible file-scope object/function redeclarations with recursive type checking and composite array/prototype retention, local/global variables with initializers, C11 `_Static_assert(integer-constant-expression, "message")` at file and block scope, `{ }` brace-enclosed initializers for arrays and structs, character-array initialization from string literals with safe length inference/zero-fill, array length inference from initializer, function definitions, prototypes with named or unnamed parameters, standard void/variadic parameter-list constraints, incomplete-record prototypes that must be complete by function definition, non-array/non-function return-type constraints (including typedef-hidden shapes), abstract callback declarators, parameter array/function adjustment including outermost `[]` qualifiers and constant-bound `static` array parameters, C-compatible old-style `f()` versus prototype compatibility using default argument promotions (including variadic incompatibility), and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict), and expression-level assignment/return/argument compatibility checking for numeric, pointer, function-pointer, `void *`, and null-pointer values, plus record assignment/conditional compatibility within object expressions, with typed equality/relational/logical/conditional operators, conditional-result normalization, and semantic modifiable-lvalue/addressability checks for assignment, compound assignment, increment/decrement, address-of, and dereference; explicit casts enforce scalar/void target constraints and the supported arithmetic, pointer, and integer-pointer conversion categories, including bounds-checked aggregate initialization with implicit zero-fill for omitted aggregate subobjects and positional brace elision across nested arrays/records and integer-constant-expression array designators for automatic/static integer arrays
- **Lexical literals**: ordinary character/string literals support standard simple escapes plus one-to-three-digit octal and variable-length hexadecimal escapes, with byte-range diagnostics and adjacent string literal concatenation; every function provides the C99 predefined `__func__` identifier as a function-local `static const char[]` object
- **Preprocessor**: object-like and function-like macros, recursive expansion, `#include`, `#define`, `#undef`, `#if/#elif/#else/#endif`, `#ifdef/#ifndef`, `defined`, variadic macros with `__VA_ARGS__`, stringification `#`, token pasting `##`, source line splicing, and `#error`
- **Scope**: lexical block-level scoping for variables, the shared `struct`/`union`/`enum` tag namespace, typedef names, and enumeration constants, including ordinary-identifier shadowing
- **Control-flow constraints**: `if`, `while`, `do-while`, and non-empty `for` controlling expressions must have scalar type (with ordinary array/function designator decay); `break` is accepted only inside loops or `switch`, while `continue` is accepted only inside loops, including correctly nested loop/switch combinations
- **Floating point**: scalar `float`/`double` literals, variables, arithmetic, comparisons, casts, truth tests, compound assignment, increment/decrement, scalar global/static initializers, and function arguments/returns using the SysV AMD64 register/stack convention. Integer and SSE register classes exhaust independently, with overflow arguments passed on the caller stack. Direct and indirect calls use declared parameter types for scalar coercion; indirect calls accept arbitrary function-valued postfix expressions such as `(fp)(x)` and `(*fp)(x)`. External variadic calls, including indirect calls, receive the required vector-register count and default float promotion. Full-range `unsigned long` conversions to and from `float`/`double` are lowered without signed-64 truncation. Compiler-backed `va_arg` supports promoted GP/SSE scalars plus SysV-classified record values.
- **Record types**: `struct`/`union` forward declarations, completion-in-place, recursive pointer members, and block-scoped tags. Incomplete records are permitted behind pointers/`extern` declarations and rejected where object size is required. Record objects support local assignment and aggregate initialization. SysV AMD64 by-value calls/returns use per-eightbyte INTEGER/SSE classification for naturally laid-out records up to 16 bytes, including floating members, mixed integer/floating records, nested arrays/records, and INTEGER-dominant union merges; complete records larger than 16 bytes use MEMORY-class stack arguments and hidden `sret` returns, with bidirectional host-C interoperability. Record pointers remain fully supported.
- **Alignment**: C11 `_Alignof` and `_Alignas` for object/member declarations, with explicit alignment carried through stack layout, static data emission, and record layout
- **Target**: x86-64 AT&T syntax assembly, Linux System V ABI

## Build and test

The x86-64 ELF backend emits a `.note.GNU-stack` marker so generated objects do not request an executable process stack.

Run on Linux or WSL with GCC and GNU Make:

```sh
make
make test
```

The test target builds `minicc`, compiles small C programs with it, links them with the host compiler, and checks their exit values. It runs the 228 core compiler cases plus focused basic and advanced preprocessor regression suites. Use `make clean` to remove generated objects, binaries, and temporary test sources.

## Notes

The compiler is designed as an educational systems-programming project rather than a packaged commercial product.

- Function calls share prototype-aware argument coercion and C default argument promotions for variadic and unprototyped calls.

- SysV variadic callees use a GP/SSE register-save area and typed compiler-backed `va_start`/`va_arg`, including floating arguments, small INTEGER/SSE/mixed records, MEMORY-class records, whole-record register-exhaustion fallback, and stack overflow.

- `sizeof` and C11 `_Alignof` are integer constant expressions typed as LP64 `size_t` (`unsigned long`), so their signed/unsigned arithmetic follows the normal usual arithmetic conversions.

- Static/global integer scalar and array initializers accept type-aware integer constant expressions, including enum constants, casts, shifts, short-circuit logic, and ternary expressions. Signed integer constant-expression arithmetic diagnoses overflow and invalid signed left shifts instead of wrapping, while unsigned arithmetic retains modulo semantics.

- C11 `_Static_assert` reuses that integer constant-expression machinery at file and block scope, including enum, `sizeof`, and `_Alignof` queries, and reports the supplied string on assertion failure.

- Static pointer initializers support linker-relocatable address constants such as global/object addresses, array offsets, function addresses, member addresses, and string literals.

- Static aggregate initializers use zero-filled byte images plus per-offset linker relocations, supporting pointer/function/string addresses inside arrays and records, nested aggregates, designators, and record padding.

- Union types retain their record kind through semantic analysis; automatic/static union initializers select exactly one member (the first by default or a designated member), preserve overlapping storage correctly, and reject excess initializer elements.

- Static-storage objects are emitted at their declared type alignment, including initialized/uninitialized scalars, relocatable pointers, arrays, records, unions, and block-static objects.

- Character-array string initialization is supported recursively inside automatic/static aggregates, including struct/union members, multidimensional character arrays, and designated subobjects, with C-compatible NUL truncation and zero-fill.

- Record values use the SysV AMD64 by-value ABI across direct/indirect calls and returns. Records up to 16 bytes use INTEGER/SSE register classification with whole-record stack fallback when a required register class is exhausted; larger MEMORY-class records are copied through stack argument areas and hidden `sret` destinations. Variadic GP/SSE/overflow cursors and bidirectional host-GCC interoperability are regression-tested across both paths.

Static-storage floating scalars and aggregate floating subobjects accept arithmetic constant-expression initializers, including casts, conditionals, and mixed integer/floating arithmetic.

Designated aggregate initializers support nested designator lists such as `[1][2]`, `[1].field`, `.inner.x`, and `.rows[1]` for both static storage and automatic objects.

Nested braced aggregate initializer-lists accept member/array designators at every level, including positional continuation after a designator for automatic objects.

Ordinary identifiers (objects/functions, typedef names, and enumerators) now obey one lexical namespace with same-scope conflict diagnostics and correct cross-kind shadowing.


- Incomplete array types are tracked explicitly. Local/static objects without an inferred bound are rejected; file-scope `extern T a[]` remains incomplete, tentative definitions are completed to one element at translation-unit end, and initializer-based bound inference remains supported. Flexible array members are accepted only as the final member of a non-union struct with at least one preceding named member, and such structs cannot be embedded or used as array element types.
