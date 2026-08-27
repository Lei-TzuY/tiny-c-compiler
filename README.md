# Mini C Compiler

An educational C compiler implemented in C. The pipeline includes preprocessing, tokenization, parsing, type analysis, and x86-64 code generation; the shell test suite documents and exercises the supported language subset.

## Supported Language Features

- **Types**: `char` (1B), `short` (2B), `int` (4B), `long` (8B), `float` (4B), `double` (8B), `void`, pointers, arrays, `struct`, `union`, tagged `enum`, `typedef`, `unsigned`; enumerators accept integer constant expressions
- **Operators**: arithmetic, bitwise, logical, comparison, ternary `?:`, comma `,`, `sizeof`, prefix/postfix `++/--`, all compound assignments (`+= -= *= /= %= &= |= ^= <<= >>=`), type cast; pointer arithmetic follows complete-object rules with array decay, element-size scaling, compatible pointer subtraction, and rejection of `void *`/function-pointer arithmetic
- **Control flow**: `if/else`, `while`, `for` (including init declarations), `do-while`, `switch/case/default`, `break`, `continue`, `return`, `goto`/labels
- **Declarations**: recursive C declarators with pointer/array/function grouping (including arrays of function pointers and functions returning function pointers), recursive abstract type names shared by casts and `sizeof(type-name)`, compatible file-scope object/function redeclarations with recursive type checking and composite array/prototype retention, local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer, function definitions, prototypes with named or unnamed parameters, abstract callback declarators, parameter array/function adjustment, and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict), and expression-level assignment/return/argument compatibility checking for numeric, pointer, function-pointer, `void *`, null-pointer, and record values, with typed equality/relational/logical/conditional operators, conditional-result normalization, and semantic modifiable-lvalue/addressability checks for assignment, compound assignment, increment/decrement, address-of, and dereference
- **Preprocessor**: object-like and function-like macros, recursive expansion, `#include`, `#define`, `#undef`, `#if/#elif/#else/#endif`, `#ifdef/#ifndef`, `defined`, variadic macros with `__VA_ARGS__`, stringification `#`, token pasting `##`, source line splicing, and `#error`
- **Scope**: lexical block-level scoping for variables, the shared `struct`/`union`/`enum` tag namespace, typedef names, and enumeration constants, including ordinary-identifier shadowing
- **Floating point**: scalar `float`/`double` literals, variables, arithmetic, comparisons, casts, truth tests, compound assignment, increment/decrement, scalar global/static initializers, and function arguments/returns using the SysV AMD64 register/stack convention. Integer and SSE register classes exhaust independently, with overflow arguments passed on the caller stack. Direct and indirect calls use declared parameter types for scalar coercion; indirect calls accept arbitrary function-valued postfix expressions such as `(fp)(x)` and `(*fp)(x)`. External variadic calls, including indirect calls, receive the required vector-register count and default float promotion. The built-in educational `va_list` implementation remains integer-only.
- **Record types**: `struct`/`union` forward declarations, completion-in-place, recursive pointer members, and block-scoped tags. Incomplete records are permitted behind pointers/`extern` declarations and rejected where object size is required.
- **Target**: x86-64 AT&T syntax assembly, Linux System V ABI

## Build and test

Run on Linux or WSL with GCC and GNU Make:

```sh
make
make test
```

The test target builds `minicc`, compiles small C programs with it, links them with the host compiler, and checks their exit values. It runs the 228 core compiler cases plus focused basic and advanced preprocessor regression suites. Use `make clean` to remove generated objects, binaries, and temporary test sources.

## Notes

The compiler is designed as an educational systems-programming project rather than a packaged commercial product.
