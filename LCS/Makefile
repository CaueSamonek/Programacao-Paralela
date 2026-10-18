
# arquivos e diretorios
MAIN_FILE=main.c
EXEC_NAME=trab

SOURCE_DIR=src/
HEADER_DIR=includes/
OBJECT_DIR=objects/
BINARY_DIR=bin/

OBJECTS=

# compilacao
CC=gcc
CFLAGS=-Wall -Wextra --pedantic -g -I $(HEADER_DIR)
LDFLAGS=-fopenmp

all: create_dirs $(EXEC_NAME)

create_dirs:
	mkdir -p $(OBJECT_DIR) $(BINARY_DIR)

$(EXEC_NAME): $(SOURCE_DIR)$(MAIN_FILE) $(addprefix $(OBJECT_DIR), $(OBJECTS))
	$(CC) $(CFLAGS) $< $(OBJECTS) $(LDFLAGS) -o $(BINARY_DIR)$@

%.o: $(SOURCE_DIR)%.c $(HEADER_DIR)%.h
	$(CC) $(CFLAGS) -c $< -o $@

purge:
	rm -fr $(OBJECT_DIR) $(BINARY_DIR)
