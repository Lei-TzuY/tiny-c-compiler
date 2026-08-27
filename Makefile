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

clean:
	rm -f minicc *.o *~ tmp*

.PHONY: test clean
