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


KEYWORDS = {
    b"i32": "keyword",
    b"i64": "keyword",
    b"bool": "keyword",
    b"mut": "keyword",
    b"exit": "keyword",
    b"true": "keyword",
    b"false": "keyword"
}


def is_alpha(b):
    return b is not None and (65 <= b <= 90 or 97 <= b <= 122 or b == 95)


def is_digit(b):
    return b is not None and 48 <= b <= 57


def lex(data: bytes):
    lines = []
    tokens = []
    state = "START"
    start = 0
    line = 1
    col = 1
    i = 0
    in_brace = False
    brace_line = 0
    brace_col = 0

    while i <= len(data):
        b = data[i] if i < len(data) else None

        if state == "START":
            if b is None:
                if in_brace:
                    raise CompileError(f"line {brace_line}:{brace_col}: '{{' is not closed before the end of the line")
                break

            if b in (32, 9):
                i += 1
                col += 1
                continue

            if b == 10:
                if in_brace:
                    raise CompileError(f"line {brace_line}:{brace_col}: '{{' is not closed before the end of the line")
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
                    raise CompileError(f"line {line}:{col}: unexpected byte '{{'")
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
                    raise CompileError(f"line {line}:{col}: ':' must be followed by '='")
                tokens.append(Token("operator", ":=", line, col))
                i += 2
                col += 2
                continue

            if b == ord("="):
                if i + 1 < len(data) and data[i + 1] == ord("="):
                    tokens.append(Token("operator", "==", line, col))
                    i += 2
                    col += 2
                    continue
                raise CompileError(f"line {line}:{col}: expected '==' (a single '=' is not an operator)")

            if b == ord("!"):
                if i + 1 < len(data) and data[i + 1] == ord("="):
                    tokens.append(Token("operator", "!=", line, col))
                    i += 2
                    col += 2
                    continue
                raise CompileError(f"line {line}:{col}: expected '!=' (a single '!' is not an operator)")

            if b in (ord("+"), ord("-"), ord("*")):
                tokens.append(Token("operator", chr(b), line, col))
                i += 1
                col += 1
                continue

            raise CompileError(f"line {line}:{col}: unexpected byte {chr(b)!r}")

        elif state == "IDENT":
            if b is not None and (is_alpha(b) or is_digit(b)):
                i += 1
                col += 1
                continue

            word = data[start:i]
            kind = "keyword" if word in KEYWORDS else "identifier"
            tokens.append(Token(kind, word.decode("ascii"), line, col - (i - start)))
            state = "START"
            continue

        elif state == "NUMBER":
            if b is not None and is_digit(b):
                i += 1
                col += 1
                continue

            if b is not None and is_alpha(b):
                raise CompileError(f"line {line}:{col}: letter inside number")

            tokens.append(Token("constant", data[start:i].decode("ascii"), line, col - (i - start)))
            state = "START"
            continue

    if state == "IDENT":
        word = data[start:i]
        kind = "keyword" if word in KEYWORDS else "identifier"
        tokens.append(Token(kind, word.decode("ascii"), line, col - (i - start)))
    elif state == "NUMBER":
        tokens.append(Token("constant", data[start:i].decode("ascii"), line, col - (i - start)))

    if in_brace:
        raise CompileError(f"line {brace_line}:{brace_col}: '{{' is not closed before the end of the line")
    
    if tokens:
        lines.append(tokens)
        
    return lines


class Node:
    def __init__(self, line, col):
        self.line = line
        self.col = col


class ExprNode(Node):
    pass


class StmtNode(Node):
    pass


class ConstNode(ExprNode):
    def __init__(self, line, col, value):
        super().__init__(line, col)
        self.value = value

    def dump(self, indent=0):
        print(" " * indent + f"Const {self.value}")

    def accept(self, visitor):
        return visitor.visit_const(self)

    def codegen(self, builder, ctx):
        return ir.Constant(I32, self.value)


class BoolNode(ExprNode):
    def __init__(self, line, col, value):
        super().__init__(line, col)
        self.value = value

    def dump(self, indent=0):
        val_str = 'true' if self.value else 'false'
        print(" " * indent + f"Bool {val_str}")

    def accept(self, visitor):
        return visitor.visit_bool(self)

    def codegen(self, builder, ctx):
        return ir.Constant(I32, 1 if self.value else 0)


class VarNode(ExprNode):
    def __init__(self, line, col, name):
        super().__init__(line, col)
        self.name = name

    def dump(self, indent=0):
        print(" " * indent + f"Var {self.name}")

    def accept(self, visitor):
        return visitor.visit_var(self)

    def codegen(self, builder, ctx):
        return builder.load(self.decl.storage, name=f"{self.name}_val")


class BinOpNode(ExprNode):
    def __init__(self, line, col, op, left, right):
        super().__init__(line, col)
        self.op = op
        self.left = left
        self.right = right

    def dump(self, indent=0):
        print(" " * indent + f"BinOp {self.op}")
        self.left.dump(indent + 2)
        self.right.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_binop(self)

    def codegen(self, builder, ctx):
        l = self.left.codegen(builder, ctx)
        r = self.right.codegen(builder, ctx)
        
        if self.op == "+":
            return builder.add(l, r, name="addtmp")
        if self.op == "-":
            return builder.sub(l, r, name="subtmp")
        if self.op == "*":
            return builder.mul(l, r, name="multmp")
            
        return builder.icmp_signed(self.op, l, r)


class DeclNode(StmtNode):
    def __init__(self, line, col, name, type_name, mutable, init):
        super().__init__(line, col)
        self.name = name
        self.type_name = type_name
        self.mutable = mutable
        self.init = init

    def dump(self, indent=0):
        mut_str = 'mut' if self.mutable else 'const'
        print(" " * indent + f"Decl {self.name} {self.type_name} {mut_str}")
        self.init.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_decl(self)

    def codegen(self, builder, ctx):
        self.storage = builder.alloca(I32, name=self.name)
        builder.store(self.init.codegen(builder, ctx), self.storage)


class AssignNode(StmtNode):
    def __init__(self, line, col, name, value):
        super().__init__(line, col)
        self.name = name
        self.value = value

    def dump(self, indent=0):
        print(" " * indent + f"Assign {self.name}")
        self.value.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_assign(self)

    def codegen(self, builder, ctx):
        builder.store(self.value.codegen(builder, ctx), self.decl.storage)


class ExitNode(StmtNode):
    def __init__(self, line, col, value):
        super().__init__(line, col)
        self.value = value

    def dump(self, indent=0):
        print(" " * indent + "Exit")
        self.value.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_exit(self)

    def codegen(self, builder, ctx):
        val = self.value.codegen(builder, ctx)
        builder.call(ctx["printf"], [builder.bitcast(ctx["fmt"], ir.PointerType(I8)), val])
        builder.ret(ir.Constant(I32, 0))


class ProgramNode(Node):
    def __init__(self, line, col, stmts, exit_node):
        super().__init__(line, col)
        self.stmts = stmts
        self.exit_node = exit_node

    def dump(self, indent=0):
        print(" " * indent + "Program")
        for s in self.stmts:
            s.dump(indent + 2)
        self.exit_node.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_program(self)

    def codegen(self, builder, ctx):
        for s in self.stmts:
            s.codegen(builder, ctx)
        self.exit_node.codegen(builder, ctx)


class Parser:
    def __init__(self, lines):
        self.lines = lines
        self.toks = []
        self.pos = 0

    def peek(self):
        if self.pos < len(self.toks):
            return self.toks[self.pos]
        return None

    def eat(self):
        tok = self.toks[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind, what):
        tok = self.peek()
        if tok is None or tok.kind != kind:
            t = tok or (self.toks[-1] if self.toks else Token("", "", 1, 1))
            col_offset = len(t.text) if not tok else 0
            raise CompileError(f"line {t.line}:{t.col + col_offset}: expected {what}")
        return self.eat()

    def parse_program(self):
        stmts = []
        exit_node = None

        for toks in self.lines:
            if not toks:
                continue
            if toks[-1].kind == "endline":
                toks = toks[:-1]
            if not toks:
                continue
            
            self.toks = toks
            self.pos = 0
            first = toks[0]
            
            if first.text == "exit":
                if exit_node is not None:
                    raise CompileError(f"line {first.line}:{first.col}: statement after exit")
                exit_node = self.parse_exit()
            else:
                if exit_node is not None:
                    raise CompileError(f"line {first.line}:{first.col}: statement after exit")
                stmts.append(self.parse_statement())
                
            if self.peek() is not None:
                current_tok = self.peek()
                raise CompileError(f"line {current_tok.line}:{current_tok.col}: unexpected '{current_tok.text}' after the statement")
                
        if exit_node is None:
            raise CompileError("line 1:1: no exit statement")
            
        return ProgramNode(1, 1, stmts, exit_node)

    def parse_statement(self):
        tok = self.peek()
        if tok.text in ("i32", "i64", "bool"):
            return self.parse_decl()
        elif tok.kind == "identifier":
            return self.parse_assign()
        else:
            raise CompileError(f"line {tok.line}:{tok.col}: cannot start a statement with '{tok.text}'")

    def parse_decl(self):
        type_tok = self.eat()
        mutable = False
        
        tok = self.peek()
        if tok and tok.text == "mut":
            self.eat()
            mutable = True
            
        name = self.expect("identifier", "a variable name")
        
        tok = self.peek()
        if not tok or tok.kind != "lbrace":
            t = tok or (self.toks[-1] if self.toks else Token("", "", 1, 1))
            col_offset = len(t.text) if not tok else 0
            raise CompileError(f"line {t.line}:{t.col + col_offset}: variable '{name.text}' needs an initialiser in {{}}")
        self.eat()
        
        init = self.parse_expr()
        
        tok = self.peek()
        if not tok or tok.kind != "rbrace":
            t = tok or (self.toks[-1] if self.toks else Token("", "", 1, 1))
            col_offset = len(t.text) if not tok else 0
            raise CompileError(f"line {t.line}:{t.col + col_offset}: variable '{name.text}' needs an initialiser in {{}}")
        self.eat()
        
        return DeclNode(name.line, name.col, name.text, type_tok.text, mutable, init)

    def parse_assign(self):
        name = self.expect("identifier", "a variable name")
        tok = self.peek()
        
        if tok is None or tok.text != ":=":
            t = tok or name
            col_offset = len(t.text) if not tok else 0
            got_str = 'end of line' if not tok else repr(tok.text)
            raise CompileError(f"line {t.line}:{t.col + col_offset}: expected ':=' after '{name.text}', got {got_str}")
            
        self.eat()
        return AssignNode(name.line, name.col, name.text, self.parse_expr())

    def parse_exit(self):
        start = self.eat()
        return ExitNode(start.line, start.col, self.parse_factor())

    def parse_expr(self):
        node = self.parse_arith()
        tok = self.peek()
        
        if tok and tok.kind == "operator" and tok.text in ("==", "!="):
            self.eat()
            node = BinOpNode(tok.line, tok.col, tok.text, node, self.parse_arith())
            
        return node

    def parse_arith(self):
        node = self.parse_term()
        tok = self.peek()
        
        while tok and tok.kind == "operator" and tok.text in ("+", "-"):
            self.eat()
            node = BinOpNode(tok.line, tok.col, tok.text, node, self.parse_term())
            tok = self.peek()
            
        return node

    def parse_term(self):
        node = self.parse_factor()
        tok = self.peek()
        
        while tok and tok.kind == "operator" and tok.text == "*":
            self.eat()
            node = BinOpNode(tok.line, tok.col, tok.text, node, self.parse_factor())
            tok = self.peek()
            
        return node

    def parse_factor(self):
        tok = self.peek()
        
        if tok is None:
            last = self.toks[-1]
            raise CompileError(f"line {last.line}:{last.col + len(last.text)}: expected a constant or a variable, found end of line")
            
        self.eat()
        
        if tok.kind == "constant":
            return ConstNode(tok.line, tok.col, int(tok.text))
        elif tok.kind == "identifier":
            return VarNode(tok.line, tok.col, tok.text)
        elif tok.kind == "keyword" and tok.text in ("true", "false"):
            return BoolNode(tok.line, tok.col, tok.text == "true")
            
        raise CompileError(f"line {tok.line}:{tok.col}: expected a constant or a variable, got '{tok.text}'")


class SemanticChecker:
    def __init__(self):
        self.symbols = {}

    def check_assignable(self, expr, want, at, what):
        have = expr.type
        
        if isinstance(expr, ConstNode) and want == "i32" and have == "i64":
            raise CompileError(f"line {expr.line}:{expr.col}: constant {expr.value} does not fit in {want}")
            
        if have == want or (have == "i32" and want == "i64"):
            return
            
        raise CompileError(f"line {at.line}:{at.col}: cannot {what} of type {want} with a value of type {have}")

    def visit_program(self, node):
        for s in node.stmts:
            s.accept(self)
        node.exit_node.accept(self)

    def visit_decl(self, node):
        if node.name in self.symbols:
            raise CompileError(f"line {node.line}:{node.col}: variable '{node.name}' is declared twice")
            
        node.init.accept(self)
        self.check_assignable(node.init, node.type_name, node, f"initialise '{node.name}'")
        self.symbols[node.name] = node

    def visit_assign(self, node):
        if node.name not in self.symbols:
            raise CompileError(f"line {node.line}:{node.col}: variable '{node.name}' is used before its declaration")
            
        decl = self.symbols[node.name]
        if not decl.mutable:
            raise CompileError(f"line {node.line}:{node.col}: cannot assign to '{node.name}': it is not mut")
            
        node.value.accept(self)
        self.check_assignable(node.value, decl.type_name, node, f"assign to '{node.name}'")
        node.decl = decl

    def visit_exit(self, node):
        node.value.accept(self)

    def visit_binop(self, node):
        node.left.accept(self)
        node.right.accept(self)
        
        lt = node.left.type
        rt = node.right.type
        
        if node.op in ("+", "-", "*"):
            if lt == "bool":
                raise CompileError(f"line {node.line}:{node.col}: cannot apply '{node.op}' to bool")
            if rt == "bool":
                raise CompileError(f"line {node.line}:{node.col}: cannot apply '{node.op}' to bool")
                
            node.type = "i64" if "i64" in (lt, rt) else "i32"
        else:
            if (lt == "bool") != (rt == "bool"):
                raise CompileError(f"line {node.line}:{node.col}: cannot compare bool with {rt if lt == 'bool' else lt}")
                
            node.type = "bool"

    def visit_const(self, node):
        node.type = "i64" if node.value > 4294967295 else "i32"

    def visit_var(self, node):
        if node.name not in self.symbols:
            raise CompileError(f"line {node.line}:{node.col}: variable '{node.name}' is used before its declaration")
            
        node.decl = self.symbols[node.name]
        node.type = node.decl.type_name

    def visit_bool(self, node):
        node.type = "bool"


def main():
    args = sys.argv[1:]
    print_ast = False
    print_tokens = False
    
    if "--tokens" in args:
        print_tokens = True
        args.remove("--tokens")
    if "--ast" in args:
        print_ast = True
        args.remove("--ast")

    if print_ast or print_tokens:
        if len(args) != 1:
            print(f"usage: {sys.argv[0]} [--tokens | --ast] input.txt", file=sys.stderr)
            sys.exit(1)
        input_path = args[0]
        output_path = None
    else:
        if len(args) != 2:
            print(f"usage: {sys.argv[0]} [--tokens | --ast] input.txt output.ll", file=sys.stderr)
            sys.exit(1)
        input_path = args[0]
        output_path = args[1]

    module = ir.Module(name="practice4")
    module.triple = llvm.get_default_triple()
    
    main_func_type = ir.FunctionType(I32, [])
    main_function = ir.Function(module, main_func_type, name="main")
    builder = ir.IRBuilder(main_function.append_basic_block("entry"))
    
    printf_type = ir.FunctionType(I32, [ir.PointerType(I8)], var_arg=True)
    printf = ir.Function(module, printf_type, name="printf")
    
    fmt_data = bytearray(b"Program exit with result %d\n\0")
    fmt_type = ir.ArrayType(I8, len(fmt_data))
    fmt = ir.GlobalVariable(module, fmt_type, name="fmt")
    fmt.linkage = "private"
    fmt.global_constant = True
    fmt.initializer = ir.Constant(fmt_type, fmt_data)

    try:
        with open(input_path, "rb") as source:
            lines = lex(source.read())

        if print_tokens:
            for line_tokens in lines:
                for t in line_tokens:
                    print(f"({t.text}, {t.kind}, {t.line}:{t.col})")
            sys.exit(0)

        parser = Parser(lines)
        tree = parser.parse_program()

        if print_ast:
            tree.dump()
            sys.exit(0)

        checker = SemanticChecker()
        tree.accept(checker)

        ctx = {
            "printf": printf,
            "fmt": fmt
        }
        
        tree.codegen(builder, ctx)
        
        with open(output_path, "w") as out:
            out.write(str(module))

    except CompileError as e:
        print(f"compilation error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
