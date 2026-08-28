CFLAGS=-std=c11 -g -fno-common
SRCS=$(filter-out tmp.c,$(wildcard *.c))
OBJS=$(SRCS:.c=.o)

minicc: $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

$(OBJS): minicc.h

test: minicc
	./test/test.sh
	bash ./test/driver_stdin.sh
	bash ./test/driver_cli.sh
	bash ./test/preprocessor.sh
	bash ./test/preprocessor_advanced.sh
	bash ./test/predefined_macros.sh
	bash ./test/predefined_source_macros.sh
	bash ./test/float.sh
	bash ./test/float_abi.sh
	bash ./test/incomplete_tags.sh
	bash ./test/incomplete_flexible_arrays.sh
	bash ./test/typedef_scope.sh
	bash ./test/enum_scope.sh
	bash ./test/ordinary_namespace.sh
	bash ./test/enum_constexpr_tags.sh
	bash ./test/abi_stack_args.sh
	bash ./test/prototype_params.sh
	bash ./test/parameter_array_qualifiers.sh
	bash ./test/function_pointer_prototype.sh
	bash ./test/callable_declarators.sh
	bash ./test/prototype_arity.sh
	bash ./test/recursive_declarators.sh
	bash ./test/type_names.sh
	bash ./test/type_compatibility.sh
	bash ./test/semantic_assignments.sh
	bash ./test/expression_operators.sh
	bash ./test/unary_plus.sh
	bash ./test/logical_scalar.sh
	bash ./test/comparison_scalar.sh
	bash ./test/pointer_equality.sh
	bash ./test/conditional_operator.sh
	bash ./test/null_pointer_constants.sh
	bash ./test/pointer_arithmetic.sh
	bash ./test/lvalue_semantics.sh
	bash ./test/type_qualifiers.sh
	bash ./test/restrict_qualifier.sh
	bash ./test/storage_class_specifiers.sh
	bash ./test/cast_constraints.sh
	bash ./test/switch_constraints.sh
	bash ./test/nested_switch_labels.sh
	bash ./test/control_flow_context.sh
	bash ./test/control_condition_scalars.sh
	bash ./test/function_type_constraints.sh
	bash ./test/oldstyle_function_compatibility.sh
	bash ./test/arithmetic_conversions.sh
	bash ./test/alignof.sh
	bash ./test/alignas.sh
	bash ./test/noreturn.sh
	bash ./test/sizeof_alignof_size_t.sh
	bash ./test/static_assert.sh
	bash ./test/generic_selection.sh
	bash ./test/predefined_func.sh
	bash ./test/gnu_stack.sh
	bash ./test/static_object_alignment.sh
	bash ./test/uint64_fp_conversions.sh
	bash ./test/integer_literals.sh
	bash ./test/signed_specifiers.sh
	bash ./test/type_specifier_combinations.sh
	bash ./test/void_object_constraints.sh
	bash ./test/block_extern_initializer.sh
	bash ./test/char_type_identity.sh
	bash ./test/escape_sequences.sh
	bash ./test/constant_expressions.sh
	bash ./test/static_integer_initializers.sh
	bash ./test/static_floating_initializers.sh
	bash ./test/static_address_initializers.sh
	bash ./test/aggregate_static_relocations.sh
	bash ./test/union_initializers.sh
	bash ./test/aggregate_initializers.sh
	bash ./test/brace_elision.sh
	bash ./test/array_designators.sh
	bash ./test/nested_designators.sh
	bash ./test/nested_brace_designators.sh
	bash ./test/call_arguments.sh
	bash ./test/record_abi_firewall.sh
	bash ./test/sysv_record_abi.sh
	bash ./test/sysv_sse_record_abi.sh
	bash ./test/sysv_memory_record_abi.sh
	bash ./test/sysv_mixed_union_abi.sh
	bash ./test/string_array_initializers.sh
	bash ./test/nested_string_initializers.sh
	bash ./test/sysv_variadic_callee.sh
	bash ./test/sysv_variadic_record_va_arg.sh

clean:
	rm -f minicc *.o *~ tmp*

.PHONY: test clean
