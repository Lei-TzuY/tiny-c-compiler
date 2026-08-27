CFLAGS=-std=c11 -g -fno-common
SRCS=$(filter-out tmp.c,$(wildcard *.c))
OBJS=$(SRCS:.c=.o)

minicc: $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

$(OBJS): minicc.h

test: minicc
	./test/test.sh
	bash ./test/preprocessor.sh
	bash ./test/preprocessor_advanced.sh
	bash ./test/float.sh
	bash ./test/float_abi.sh
	bash ./test/incomplete_tags.sh
	bash ./test/typedef_scope.sh
	bash ./test/enum_scope.sh
	bash ./test/enum_constexpr_tags.sh
	bash ./test/abi_stack_args.sh
	bash ./test/prototype_params.sh
	bash ./test/function_pointer_prototype.sh
	bash ./test/callable_declarators.sh
	bash ./test/prototype_arity.sh
	bash ./test/recursive_declarators.sh
	bash ./test/type_names.sh
	bash ./test/type_compatibility.sh
	bash ./test/semantic_assignments.sh
	bash ./test/expression_operators.sh
	bash ./test/pointer_arithmetic.sh
	bash ./test/lvalue_semantics.sh
	bash ./test/type_qualifiers.sh
	bash ./test/cast_constraints.sh
	bash ./test/switch_constraints.sh
	bash ./test/nested_switch_labels.sh
	bash ./test/arithmetic_conversions.sh
	bash ./test/gnu_stack.sh

clean:
	rm -f minicc *.o *~ tmp*

.PHONY: test clean
