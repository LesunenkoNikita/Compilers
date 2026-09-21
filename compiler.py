import sys

from llvmlite import ir
import llvmlite.binding as llvm


I32 = ir.IntType(32)
I8 = ir.IntType(8)


class CompileError(Exception):
    pass


class Token:
    def __init__(self, kind, text, line, col):
        self.kind = kind
        self.text = text
        self.line = line
        self.col = col

    def __repr__(self):
        return f"Token({self.kind!r}, {self.text!r}, {self.line}, {self.col})"


KEYWORDS = {
    b"i32": "keyword",
    b"mut": "keyword",
    b"exit": "keyword",
}


def is_alpha(b):
    return (
        b is not None
        and (
            65 <= b <= 90
            or 97 <= b <= 122
            or b == 95
        )
    )


def is_digit(b):
    return b is not None and 48 <= b <= 57


def lex(data: bytes):
    lines = []
    tokens = []

    state = "START"
    start = 0
    in_brace = False
    brace_line = 0
    brace_col = 0

    line = 1
    col = 1

    i = 0

    while i <= len(data):
        b = data[i] if i < len(data) else None

        if state == "START":
            if b is None:
                if in_brace:
                    raise CompileError(
                        f"line {brace_line}:{brace_col}: "
                        "'{' is not closed before the end of the line"
                    )
                break

            if b == 32 or b == 9:
                i += 1
                col += 1
                continue

            if b == 10:
                if in_brace:
                    raise CompileError(
                        f"line {brace_line}:{brace_col}: "
                        "'{' is not closed before the end of the line"
                    )
                tokens.append(Token("endline", "\n", line, col))
                lines.append(tokens)
                tokens = []

                line += 1
                col = 1
                i += 1
                continue

            if is_alpha(b):
                state = "IDENT"
                start = i
                i += 1
                col += 1
                continue

            if is_digit(b):
                state = "NUMBER"
                start = i
                i += 1
                col += 1
                continue

            if b == ord("{"):
                if in_brace:
                    raise CompileError(
                        f"line {line}:{col}: unexpected byte '{{'"
                    )
                tokens.append(Token("lbrace", "{", line, col))
                in_brace = True
                brace_line = line
                brace_col = col
                i += 1
                col += 1
                continue

            if b == ord("}"):
                tokens.append(Token("rbrace", "}", line, col))
                in_brace = False
                i += 1
                col += 1
                continue

            if b == ord(":"):
                if i + 1 >= len(data) or data[i + 1] != ord("="):
                    raise CompileError(
                        f"line {line}:{col}: ':' must be followed by '='"
                    )

                tokens.append(Token("operator", ":=", line, col))
                i += 2
                col += 2
                continue

            if b == ord("="):
                raise CompileError(
                    f"line {line}:{col}: unexpected byte '='"
                )

            if b == ord("+"):
                tokens.append(Token("operator", "+", line, col))
                i += 1
                col += 1
                continue

            if b == ord("-"):
                tokens.append(Token("operator", "-", line, col))
                i += 1
                col += 1
                continue

            if b == ord("*"):
                tokens.append(Token("operator", "*", line, col))
                i += 1
                col += 1
                continue

            raise CompileError(
                f"line {line}:{col}: unexpected byte {chr(b)!r}"
            )

        elif state == "IDENT":
            if b is not None and (is_alpha(b) or is_digit(b)):
                i += 1
                col += 1
                continue

            word = data[start:i]

            if word in KEYWORDS:
                kind = "keyword"
            else:
                kind = "identifier"

            tokens.append(
                Token(
                    kind,
                    word.decode("ascii"),
                    line,
                    col - (i - start)
                )
            )

            state = "START"
            continue

        elif state == "NUMBER":
            if b is not None and is_digit(b):
                i += 1
                col += 1
                continue

            if b is not None and is_alpha(b):
                raise CompileError(
                    f"line {line}:{col}: letter inside number"
                )

            number = data[start:i]

            tokens.append(
                Token(
                    "constant",
                    number.decode("ascii"),
                    line,
                    col - (i - start)
                )
            )

            state = "START"
            continue

    if state == "IDENT":
        word = data[start:i]

        if word in KEYWORDS:
            kind = "keyword"
        else:
            kind = "identifier"

        tokens.append(
            Token(
                kind,
                word.decode("ascii"),
                line,
                col - (i - start)
            )
        )

    elif state == "NUMBER":
        number = data[start:i]

        tokens.append(
            Token(
                "constant",
                number.decode("ascii"),
                line,
                col - (i - start)
            )
        )

    if in_brace:
        raise CompileError(
            f"line {brace_line}:{brace_col}: "
            "'{' is not closed before the end of the line"
        )

    if tokens:
        lines.append(tokens)

    return lines


def syntax_error(token, message):
    raise CompileError(
        f"line {token.line}:{token.col}: {message}"
    )


def parse_operand(tokens, index, symbols):
    token = tokens[index]

    if token.kind == "constant":
        return ir.Constant(I32, int(token.text)), index + 1

    if token.kind == "identifier":
        if token.text not in symbols:
            syntax_error(
                token,
                f"variable '{token.text}' is used before its declaration"
            )

        value = builder.load(
            symbols[token.text]["storage"],
            name=f"{token.text}_value"
        )

        return value, index + 1

    syntax_error(
        token,
        f"expected constant or variable, got '{token.text}'"
    )


def parse_expression(tokens, index, symbols):
    lhs, index = parse_operand(
        tokens,
        index,
        symbols
    )

    if index >= len(tokens):
        return lhs, index

    token = tokens[index]

    if token.kind != "operator" or token.text not in ("+", "-", "*"):
        return lhs, index

    operator = token.text

    rhs, index = parse_operand(
        tokens,
        index + 1,
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

    else:
        result = builder.mul(
            lhs,
            rhs,
            name="multmp"
        )

    return result, index


def parse_declaration(tokens, symbols):
    index = 1

    mutable = False

    if index < len(tokens) and tokens[index].text == "mut":
        mutable = True
        index += 1

    if index >= len(tokens):
        last = tokens[-1]
        token = Token("error", "", last.line, last.col + len(last.text))
        syntax_error(
            token,
            "expected variable name"
        )

    name_token = tokens[index]

    if name_token.kind != "identifier":
        syntax_error(
            name_token,
            f"expected variable name, got '{name_token.text}'"
        )

    name = name_token.text

    if name in symbols:
        syntax_error(
            name_token,
            f"variable '{name}' is declared twice"
        )

    index += 1

    if index >= len(tokens) or tokens[index].kind != "lbrace":
        token = (
            tokens[index]
            if index < len(tokens)
            else Token("error", "", name_token.line, name_token.col + len(name_token.text))
        )

        syntax_error(
            token,
            f"variable '{name}' needs an initialiser in {{}}"
        )

    index += 1

    if index >= len(tokens) or tokens[index].kind == "rbrace":
        token = (
            tokens[index]
            if index < len(tokens)
            else Token("error", "", tokens[-1].line, tokens[-1].col + len(tokens[-1].text))
        )

        syntax_error(
            token,
            f"variable '{name}' needs an initialiser in {{}}"
        )

    value, index = parse_expression(
        tokens,
        index,
        symbols
    )

    if index >= len(tokens) or tokens[index].kind != "rbrace":
        token = (
            tokens[index]
            if index < len(tokens)
            else Token("error", "", tokens[-1].line, tokens[-1].col + len(tokens[-1].text))
        )

        syntax_error(
            token,
            "expected '}'"
        )

    index += 1

    if index < len(tokens):
        syntax_error(
            tokens[index],
            f"unexpected token '{tokens[index].text}'"
        )

    symbols[name] = {
        "storage": builder.alloca(
            I32,
            name=name
        ),
        "mut": mutable
    }

    builder.store(
        value,
        symbols[name]["storage"]
    )


def parse_assignment(tokens, symbols):
    destination_token = tokens[0]
    destination = destination_token.text

    if destination not in symbols:
        syntax_error(
            destination_token,
            f"variable '{destination}' is used before its declaration"
        )

    if not symbols[destination]["mut"]:
        syntax_error(
            destination_token,
            f"cannot assign to '{destination}': it is not mut"
        )

    if len(tokens) < 3 or tokens[1].text != ":=":
        token = tokens[1] if len(tokens) > 1 else Token("error", "", destination_token.line, destination_token.col + len(destination_token.text))
        syntax_error(
            token,
            "expected ':='"
        )

    value, index = parse_expression(
        tokens,
        2,
        symbols
    )

    if index < len(tokens):
        syntax_error(
            tokens[index],
            f"unexpected token '{tokens[index].text}'"
        )

    builder.store(
        value,
        symbols[destination]["storage"]
    )


def parse_exit(tokens, symbols):
    if len(tokens) < 2:
        syntax_error(
            tokens[-1],
            "exit needs a constant or variable"
        )

    token = tokens[1]

    if token.kind == "constant":
        value = ir.Constant(
            I32,
            int(token.text)
        )

    elif token.kind == "identifier":
        if token.text not in symbols:
            syntax_error(
                token,
                f"variable '{token.text}' is used before its declaration"
            )

        value = builder.load(
            symbols[token.text]["storage"],
            name=f"{token.text}_exit"
        )

    else:
        syntax_error(
            token,
            f"expected constant or variable, got '{token.text}'"
        )

    if len(tokens) > 2:
        syntax_error(
            tokens[2],
            f"unexpected token '{tokens[2].text}'"
        )

    fmt_pointer = builder.bitcast(
        fmt,
        ir.PointerType(I8)
    )

    builder.call(
        printf,
        [fmt_pointer, value]
    )

    builder.ret(
        ir.Constant(I32, 0)
    )


def parse_line(tokens, symbols):
    if not tokens:
        return False

    if tokens[-1].kind == "endline":
        tokens = tokens[:-1]

    if not tokens:
        return False

    first = tokens[0]

    if first.text == "i32":
        parse_declaration(
            tokens,
            symbols
        )
        return False

    if first.text == "exit":
        parse_exit(
            tokens,
            symbols
        )
        return True

    if first.kind == "identifier":
        parse_assignment(
            tokens,
            symbols
        )
        return False

    syntax_error(
        first,
        f"unparsable statement starting with '{first.text}'"
    )


def main():
    args = sys.argv[1:]
    print_tokens = False

    if "--tokens" in args:
        print_tokens = True
        args.remove("--tokens")

    if print_tokens:
        if len(args) != 1:
            print(f"usage: {sys.argv[0]} --tokens input.txt", file=sys.stderr)
            sys.exit(1)
        input_path = args[0]
        output_path = None
    else:
        if len(args) != 2:
            print(f"usage: {sys.argv[0]} [--tokens] input.txt output.ll", file=sys.stderr)
            sys.exit(1)
        input_path = args[0]
        output_path = args[1]

    global builder
    global printf
    global fmt

    module = ir.Module(name="practice2")
    module.triple = llvm.get_default_triple()

    main_function_type = ir.FunctionType(
        I32,
        []
    )

    main_function = ir.Function(
        module,
        main_function_type,
        name="main"
    )

    entry_block = main_function.append_basic_block(
        "entry"
    )

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

    fmt_type = ir.ArrayType(
        I8,
        len(text)
    )

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

    try:
        with open(input_path, "rb") as source:
            data = source.read()

        lines = lex(data)

        if print_tokens:
            for line_tokens in lines:
                for token in line_tokens:
                    print(f"({token.text}, {token.kind}, {token.line}:{token.col})")
            sys.exit(0)

        symbols = {}
        exit_seen = False

        for tokens in lines:
            if exit_seen:
                token = tokens[0] if tokens else Token(
                    "endline",
                    "\n",
                    1,
                    1
                )

                syntax_error(
                    token,
                    "statement after exit"
                )

            did_exit = parse_line(
                tokens,
                symbols
            )

            if did_exit:
                exit_seen = True

        if not exit_seen:
            if lines:
                last_line = lines[-1]

                if last_line:
                    last = last_line[-1]
                    error_line = last.line
                    error_col = last.col + len(last.text)
                else:
                    error_line = len(lines) + 1
                    error_col = 1
            else:
                error_line = 1
                error_col = 1

            raise CompileError(
                f"line {error_line}:{error_col}: no exit statement"
            )

        with open(output_path, "w") as output:
            output.write(str(module))

    except OSError as e:
        print(
            f"compilation error: {e}",
            file=sys.stderr
        )
        sys.exit(1)

    except CompileError as e:
        print(
            f"compilation error: {e}",
            file=sys.stderr
        )

        if output_path:
            try:
                import os
                if os.path.exists(output_path):
                    os.remove(output_path)
            except OSError:
                pass

        sys.exit(1)


if __name__ == "__main__":
    main()
