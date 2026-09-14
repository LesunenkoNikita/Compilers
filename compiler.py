import sys
import re

from llvmlite import ir
import llvmlite.binding as llvm

I32 = ir.IntType(32)
I8 = ir.IntType(8)


def compilation_error(line_number, message):
    print(f"compilation error: line {line_number}: {message}",
          file=sys.stderr)
    sys.exit(1)


def parse_operand(text, line_number, symbols):
    text = text.strip()

    if re.fullmatch(r"\d+", text):
        return ir.Constant(I32, int(text))

    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        if text == "int" or text == "exit":
            compilation_error(
                line_number,
                f"'{text}' is a reserved word"
            )

        if text not in symbols:
            compilation_error(
                line_number,
                f"undeclared variable '{text}'"
            )

        return builder.load(symbols[text], name=f"{text}_value")

    compilation_error(
        line_number,
        f"invalid operand '{text}'"
    )


def main():
    if len(sys.argv) != 3:
        print(
            f"usage: {sys.argv[0]} input.txt output.ll",
            file=sys.stderr
        )
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    global builder

    module = ir.Module(name="practice1")
    module.triple = llvm.get_default_triple()

    main_function_type = ir.FunctionType(I32, [])

    main_function = ir.Function(
        module,
        main_function_type,
        name="main"
    )

    entry_block = main_function.append_basic_block("entry")
    builder = ir.IRBuilder(entry_block)

    printf_type = ir.FunctionType(
        I32,
        [ir.PointerType(I8)],
        var_arg=True
    )

    printf = ir.Function(
        module,
        printf_type,
        name="printf"
    )

    text = b"Program exit with result %d\n\0"

    fmt_type = ir.ArrayType(I8, len(text))

    fmt = ir.GlobalVariable(
        module,
        fmt_type,
        name="fmt"
    )

    fmt.linkage = "private"
    fmt.global_constant = True
    fmt.initializer = ir.Constant(
        fmt_type,
        bytearray(text)
    )

    symbols = {}

    try:
        with open(input_path, "r") as source:
            lines = source.readlines()

    except OSError as e:
        print(f"compilation error: {e}", file=sys.stderr)
        sys.exit(1)

    exit_seen = False

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        if not line:
            compilation_error(
                line_number,
                "empty line"
            )

        if exit_seen:
            compilation_error(
                line_number,
                "statement after exit"
            )

        declaration_match = re.fullmatch(
            r"int\s+([A-Za-z_][A-Za-z0-9_]*)",
            line
        )

        if declaration_match:
            name = declaration_match.group(1)

            if name in ("int", "exit"):
                compilation_error(
                    line_number,
                    f"'{name}' is a reserved word"
                )

            if name in symbols:
                compilation_error(
                    line_number,
                    f"redeclared variable '{name}'"
                )

            symbols[name] = builder.alloca(
                I32,
                name=name
            )

            continue

        exit_match = re.fullmatch(
            r"exit\s+([A-Za-z_][A-Za-z0-9_]*)",
            line
        )

        if exit_match:
            name = exit_match.group(1)

            if name not in symbols:
                compilation_error(
                    line_number,
                    f"undeclared variable '{name}'"
                )

            value = builder.load(
                symbols[name],
                name=f"{name}_exit"
            )

            fmt_pointer = builder.bitcast(
                fmt,
                ir.PointerType(I8)
            )

            builder.call(
                printf,
                [fmt_pointer, value]
            )

            builder.ret(ir.Constant(I32, 0))

            exit_seen = True
            continue

        assignment_match = re.fullmatch(
            r"([A-Za-z_][A-Za-z0-9_]*)\s*:=\s*(.+)",
            line
        )

        if assignment_match:
            destination = assignment_match.group(1)
            expression = assignment_match.group(2).strip()

            if destination not in symbols:
                compilation_error(
                    line_number,
                    f"undeclared variable '{destination}'"
                )

            operation_match = re.fullmatch(
                r"(.+?)\s*([+\-*])\s*(.+)",
                expression
            )

            if operation_match:
                left_text = operation_match.group(1).strip()
                operator = operation_match.group(2)
                right_text = operation_match.group(3).strip()

                lhs = parse_operand(
                    left_text,
                    line_number,
                    symbols
                )

                rhs = parse_operand(
                    right_text,
                    line_number,
                    symbols
                )

                if operator == "+":
                    result = builder.add(
                        lhs,
                        rhs,
                        name="addtmp"
                    )

                elif operator == "-":
                    result = builder.sub(
                        lhs,
                        rhs,
                        name="subtmp"
                    )

                elif operator == "*":
                    result = builder.mul(
                        lhs,
                        rhs,
                        name="multmp"
                    )

                else:
                    compilation_error(
                        line_number,
                        f"unknown operator '{operator}'"
                    )

                builder.store(
                    result,
                    symbols[destination]
                )

                continue

            value = parse_operand(
                expression,
                line_number,
                symbols
            )

            builder.store(
                value,
                symbols[destination]
            )

            continue

        compilation_error(
            line_number,
            "unparsable line"
        )

    if not exit_seen:
        print(
            f"compilation error: line {len(lines) + 1}: no exit statement",
            file=sys.stderr
        )
        sys.exit(1)

    try:
        with open(output_path, "w") as output:
            output.write(str(module))

    except OSError as e:
        print(f"compilation error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
