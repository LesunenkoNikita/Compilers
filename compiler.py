import sys


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
    brace_line = 0
    brace_col = 0
    in_brace = False

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
                tokens.append(
                    Token("endline", "\n", line, col)
                )
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
                tokens.append(
                    Token("lbrace", "{", line, col)
                )

                brace_line = line
                brace_col = col
                in_brace = True

                i += 1
                col += 1
                continue

            if b == ord("}"):
                tokens.append(
                    Token("rbrace", "}", line, col)
                )
                in_brace = False
                i += 1
                col += 1
                continue

            if b == ord(":"):
                if i + 1 >= len(data) or data[i + 1] != ord("="):
                    raise CompileError(
                        f"line {line}:{col}: ':' must be followed by '='"
                    )

                tokens.append(
                    Token("operator", ":=", line, col)
                )

                i += 2
                col += 2
                continue

            if b == ord("="):
                raise CompileError(
                    f"line {line}:{col}: unexpected byte '='"
                )

            if b == ord("+"):
                tokens.append(
                    Token("operator", "+", line, col)
                )
                i += 1
                col += 1
                continue

            if b == ord("-"):
                tokens.append(
                    Token("operator", "-", line, col)
                )
                i += 1
                col += 1
                continue

            if b == ord("*"):
                tokens.append(
                    Token("operator", "*", line, col)
                )
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


def print_tokens(lines):
    for line_tokens in lines:
        for token in line_tokens:
            print(
                f"({token.text}, {token.kind}, "
                f"{token.line}, {token.col})"
            )


def main():
    if len(sys.argv) != 2:
        print(
            f"usage: {sys.argv[0]} input.txt",
            file=sys.stderr
        )
        sys.exit(1)

    try:
        with open(sys.argv[1], "rb") as source:
            data = source.read()

        lines = lex(data)
        print_tokens(lines)

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
        sys.exit(1)


if __name__ == "__main__":
    main()
