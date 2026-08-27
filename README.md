# Mini C Compiler

An educational C compiler implemented in C. The pipeline includes preprocessing, tokenization, parsing, type analysis, and x86-64 code generation; the shell test suite documents and exercises the supported language subset.

## Supported Language Features

- **Types**: `char` (1B), `short` (2B), `int` (4B), `long`/`long long` (8B with distinct C ranks), `float` (4B), `double` (8B), `void`, pointers, arrays, `struct`, `union`, tagged `enum`, `typedef`, `unsigned`, typed integer literal suffixes (`U`, `L`, `UL`, `LL`, `ULL`), semantic `const`/`volatile` qualifiers (including pointer qualifiers and qualifier-safe pointer conversions); enumerators accept integer constant expressions
- **Operators**: arithmetic, bitwise, logical, comparison, ternary `?:`, comma `,`, `sizeof`, prefix/postfix `++/--`, all compound assignments (`+= -= *= /= %= &= |= ^= <<= >>=`), type cast; pointer arithmetic follows complete-object rules with array decay, element-size scaling, compatible pointer subtraction, and rejection of `void *`/function-pointer arithmetic; integer promotions and LP64 usual arithmetic conversions drive mixed signed/unsigned arithmetic, comparison, shifts, and compound division/remainder/right-shift code generation
- **Control flow**: `if/else`, `while`, `for` (including init declarations), `do-while`, `switch/case/default` with integer controlling expressions, integer-constant-expression cases, promoted case-value normalization, duplicate case/default diagnostics, and case/default labeled statements nested inside blocks/conditionals/loops, `break`, `continue`, `return`, `goto`/labels
- **Declarations**: recursive C declarators with pointer/array/function grouping (including arrays of function pointers and functions returning function pointers), recursive abstract type names shared by casts and `sizeof(type-name)`, compatible file-scope object/function redeclarations with recursive type checking and composite array/prototype retention, local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, character-array initialization from string literals with safe length inference/zero-fill, array length inference from initializer, function definitions, prototypes with named or unnamed parameters, abstract callback declarators, parameter array/function adjustment, and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict), and expression-level assignment/return/argument compatibility checking for numeric, pointer, function-pointer, `void *`, and null-pointer values, plus record assignment/conditional compatibility within object expressions, with typed equality/relational/logical/conditional operators, conditional-result normalization, and semantic modifiable-lvalue/addressability checks for assignment, compound assignment, increment/decrement, address-of, and dereference; explicit casts enforce scalar/void target constraints and the supported arithmetic, pointer, and integer-pointer conversion categories, including bounds-checked aggregate initialization with implicit zero-fill for omitted aggregate subobjects and positional brace elision across nested arrays/records and integer-constant-expression array designators for automatic/static integer arrays
- **Lexical literals**: ordinary character/string literals support standard simple escapes plus one-to-three-digit octal and variable-length hexadecimal escapes, with byte-range diagnostics and adjacent string literal concatenation
- **Preprocessor**: object-like and function-like macros, recursive expansion, `#include`, `#define`, `#undef`, `#if/#elif/#else/#endif`, `#ifdef/#ifndef`, `defined`, variadic macros with `__VA_ARGS__`, stringification `#`, token pasting `##`, source line splicing, and `#error`
- **Scope**: lexical block-level scoping for variables, the shared `struct`/`union`/`enum` tag namespace, typedef names, and enumeration constants, including ordinary-identifier shadowing
- **Floating point**: scalar `float`/`double` literals, variables, arithmetic, comparisons, casts, truth tests, compound assignment, increment/decrement, scalar global/static initializers, and function arguments/returns using the SysV AMD64 register/stack convention. Integer and SSE register classes exhaust independently, with overflow arguments passed on the caller stack. Direct and indirect calls use declared parameter types for scalar coercion; indirect calls accept arbitrary function-valued postfix expressions such as `(fp)(x)` and `(*fp)(x)`. External variadic calls, including indirect calls, receive the required vector-register count and default float promotion. Full-range `unsigned long` conversions to and from `float`/`double` are lowered without signed-64 truncation. The built-in educational `va_list` implementation remains integer-only.
- **Record types**: `struct`/`union` forward declarations, completion-in-place, recursive pointer members, and block-scoped tags. Incomplete records are permitted behind pointers/`extern` declarations and rejected where object size is required. Record objects support local assignment and aggregate initialization. SysV AMD64 by-value calls/returns support naturally laid-out records up to 16 bytes with per-eightbyte INTEGER/SSE classification, including floating members, mixed integer/floating records, nested arrays/records, and INTEGER-dominant union merges; larger MEMORY-class records remain diagnosed at actual ABI boundaries, while record pointers are fully supported.
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

- SysV variadic callees use a GP/SSE register-save area and typed compiler-backed `va_start`/`va_arg`, including floating variadic arguments and stack overflow.

- Static/global integer scalar and array initializers accept type-aware integer constant expressions, including enum constants, casts, shifts, short-circuit logic, and ternary expressions.

- Static pointer initializers support linker-relocatable address constants such as global/object addresses, array offsets, function addresses, member addresses, and string literals.

- Static aggregate initializers use zero-filled byte images plus per-offset linker relocations, supporting pointer/function/string addresses inside arrays and records, nested aggregates, designators, and record padding.

- Union types retain their record kind through semantic analysis; automatic/static union initializers select exactly one member (the first by default or a designated member), preserve overlapping storage correctly, and reject excess initializer elements.

- Static-storage objects are emitted at their declared type alignment, including initialized/uninitialized scalars, relocatable pointers, arrays, records, unions, and block-static objects.

- Character-array string initialization is supported recursively inside automatic/static aggregates, including struct/union members, multidimensional character arrays, and designated subobjects, with C-compatible NUL truncation and zero-fill.

- Small records use SysV AMD64 per-eightbyte INTEGER/SSE classification across direct/indirect calls and returns. GP/XMM pools are tracked independently; if either class cannot fit an aggregate, the whole record falls back to the stack without consuming the other class, and bidirectional host-GCC interoperability is regression-tested.

Static-storage floating scalars and aggregate floating subobjects accept arithmetic constant-expression initializers, including casts, conditionals, and mixed integer/floating arithmetic.
