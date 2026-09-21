import sys
from llvmlite import ir
import llvmlite.binding as llvm

I32 = ir.IntType(32)
I8 = ir.IntType(8)

class CompileError(Exception): pass

class Token:
    def __init__(self, kind, text, line, col):
        self.kind, self.text, self.line, self.col = kind, text, line, col

KEYWORDS = {b"i32": "keyword", b"mut": "keyword", b"exit": "keyword"}

def is_alpha(b): return b is not None and (65 <= b <= 90 or 97 <= b <= 122 or b == 95)
def is_digit(b): return b is not None and 48 <= b <= 57

def lex(data: bytes):
    lines, tokens = [], []
    state, start, line, col, i = "START", 0, 1, 1, 0
    in_brace, brace_line, brace_col = False, 0, 0

    while i <= len(data):
        b = data[i] if i < len(data) else None
        if state == "START":
            if b is None:
                if in_brace: raise CompileError(f"line {brace_line}:{brace_col}: '{{' is not closed before the end of the line")
                break
            if b in (32, 9): i += 1; col += 1; continue
            if b == 10:
                if in_brace: raise CompileError(f"line {brace_line}:{brace_col}: '{{' is not closed before the end of the line")
                tokens.append(Token("endline", "\n", line, col))
                lines.append(tokens)
                tokens = []; line += 1; col = 1; i += 1; continue
            if is_alpha(b): state, start = "IDENT", i; i += 1; col += 1; continue
            if is_digit(b): state, start = "NUMBER", i; i += 1; col += 1; continue
            if b == ord("{"):
                if in_brace: raise CompileError(f"line {line}:{col}: unexpected byte '{{'")
                tokens.append(Token("lbrace", "{", line, col))
                in_brace, brace_line, brace_col = True, line, col; i += 1; col += 1; continue
            if b == ord("}"):
                tokens.append(Token("rbrace", "}", line, col))
                in_brace = False; i += 1; col += 1; continue
            if b == ord(":"):
                if i + 1 >= len(data) or data[i + 1] != ord("="): raise CompileError(f"line {line}:{col}: ':' must be followed by '='")
                tokens.append(Token("operator", ":=", line, col))
                i += 2; col += 2; continue
            if b == ord("="): raise CompileError(f"line {line}:{col}: unexpected byte '='")
            if b in (ord("+"), ord("-"), ord("*")):
                tokens.append(Token("operator", chr(b), line, col))
                i += 1; col += 1; continue
            raise CompileError(f"line {line}:{col}: unexpected byte {chr(b)!r}")
        elif state == "IDENT":
            if b is not None and (is_alpha(b) or is_digit(b)): i += 1; col += 1; continue
            word = data[start:i]
            kind = "keyword" if word in KEYWORDS else "identifier"
            tokens.append(Token(kind, word.decode("ascii"), line, col - (i - start)))
            state = "START"; continue
        elif state == "NUMBER":
            if b is not None and is_digit(b): i += 1; col += 1; continue
            if b is not None and is_alpha(b): raise CompileError(f"line {line}:{col}: letter inside number")
            number = data[start:i]
            tokens.append(Token("constant", number.decode("ascii"), line, col - (i - start)))
            state = "START"; continue
    if state == "IDENT":
        word = data[start:i]
        kind = "keyword" if word in KEYWORDS else "identifier"
        tokens.append(Token(kind, word.decode("ascii"), line, col - (i - start)))
    elif state == "NUMBER":
        number = data[start:i]
        tokens.append(Token("constant", number.decode("ascii"), line, col - (i - start)))
    if in_brace: raise CompileError(f"line {brace_line}:{brace_col}: '{{' is not closed before the end of the line")
    if tokens: lines.append(tokens)
    return lines

class Node:
    def __init__(self, line, col): self.line, self.col = line, col
class ExprNode(Node): pass
class StmtNode(Node): pass

class ConstNode(ExprNode):
    def __init__(self, line, col, value):
        super().__init__(line, col); self.value = value
    def dump(self, indent=0): print(" " * indent + f"Const {self.value}")
    def codegen(self, builder, symbols): return ir.Constant(I32, self.value)

class VarNode(ExprNode):
    def __init__(self, line, col, name):
        super().__init__(line, col); self.name = name
    def dump(self, indent=0): print(" " * indent + f"Var {self.name}")
    def codegen(self, builder, symbols):
        if self.name not in symbols: raise CompileError(f"line {self.line}:{self.col}: variable '{self.name}' is used before its declaration")
        return builder.load(symbols[self.name]["storage"], name=f"{self.name}_val")

class BinOpNode(ExprNode):
    def __init__(self, line, col, op, left, right):
        super().__init__(line, col); self.op, self.left, self.right = op, left, right
    def dump(self, indent=0):
        print(" " * indent + f"BinOp {self.op}")
        self.left.dump(indent + 2)
        self.right.dump(indent + 2)
    def codegen(self, builder, symbols):
        l = self.left.codegen(builder, symbols)
        r = self.right.codegen(builder, symbols)
        if self.op == "+": return builder.add(l, r, name="addtmp")
        if self.op == "-": return builder.sub(l, r, name="subtmp")
        if self.op == "*": return builder.mul(l, r, name="multmp")

class DeclNode(StmtNode):
    def __init__(self, line, col, name, mutable, init):
        super().__init__(line, col); self.name, self.mutable, self.init = name, mutable, init
    def dump(self, indent=0):
        m = "mut" if self.mutable else "const"
        print(" " * indent + f"Decl {self.name} {m}")
        self.init.dump(indent + 2)
    def codegen(self, builder, symbols):
        if self.name in symbols: raise CompileError(f"line {self.line}:{self.col}: variable '{self.name}' is declared twice")
        val = self.init.codegen(builder, symbols)
        alloc = builder.alloca(I32, name=self.name)
        builder.store(val, alloc)
        symbols[self.name] = {"storage": alloc, "mut": self.mutable}

class AssignNode(StmtNode):
    def __init__(self, line, col, name, value):
        super().__init__(line, col); self.name, self.value = name, value
    def dump(self, indent=0):
        print(" " * indent + f"Assign {self.name}")
        self.value.dump(indent + 2)
    def codegen(self, builder, symbols):
        if self.name not in symbols: raise CompileError(f"line {self.line}:{self.col}: variable '{self.name}' is used before its declaration")
        if not symbols[self.name]["mut"]: raise CompileError(f"line {self.line}:{self.col}: cannot assign to '{self.name}': it is not mut")
        val = self.value.codegen(builder, symbols)
        builder.store(val, symbols[self.name]["storage"])

class ExitNode(StmtNode):
    def __init__(self, line, col, value):
        super().__init__(line, col); self.value = value
    def dump(self, indent=0):
        print(" " * indent + "Exit")
        self.value.dump(indent + 2)
    def codegen(self, builder, symbols, printf, fmt):
        val = self.value.codegen(builder, symbols)
        fmt_ptr = builder.bitcast(fmt, ir.PointerType(I8))
        builder.call(printf, [fmt_ptr, val])
        builder.ret(ir.Constant(I32, 0))

class ProgramNode(Node):
    def __init__(self, line, col, stmts, exit_node):
        super().__init__(line, col); self.stmts, self.exit_node = stmts, exit_node
    def dump(self, indent=0):
        print(" " * indent + "Program")
        for s in self.stmts: s.dump(indent + 2)
        self.exit_node.dump(indent + 2)
    def codegen(self, builder, symbols, printf, fmt):
        for s in self.stmts: s.codegen(builder, symbols)
        self.exit_node.codegen(builder, symbols, printf, fmt)

class Parser:
    def __init__(self, lines):
        self.lines = lines
        self.toks = []
        self.pos = 0

    def peek(self): return self.toks[self.pos] if self.pos < len(self.toks) else None
    def eat(self): tok = self.toks[self.pos]; self.pos += 1; return tok

    def expect(self, kind, what):
        tok = self.peek()
        if tok is None or tok.kind != kind:
            line = tok.line if tok else (self.toks[-1].line if self.toks else 1)
            col = tok.col if tok else (self.toks[-1].col + len(self.toks[-1].text) if self.toks else 1)
            raise CompileError(f"line {line}:{col}: expected {what}")
        return self.eat()

    def parse_program(self):
        stmts = []
        exit_node = None
        for toks in self.lines:
            if not toks: continue
            if toks[-1].kind == "endline": toks = toks[:-1]
            if not toks: continue
            self.toks = toks
            self.pos = 0
            first = self.peek()
            if first.text == "exit":
                if exit_node is not None: raise CompileError(f"line {first.line}:{first.col}: statement after exit")
                exit_node = self.parse_exit()
            else:
                if exit_node is not None: raise CompileError(f"line {first.line}:{first.col}: statement after exit")
                stmts.append(self.parse_statement())
            if self.peek() is not None:
                tok = self.peek()
                raise CompileError(f"line {tok.line}:{tok.col}: unexpected '{tok.text}' after the statement")
        if exit_node is None: raise CompileError("line 1:1: no exit statement")
        return ProgramNode(1, 1, stmts, exit_node)

    def parse_statement(self):
        tok = self.peek()
        if tok.text == "i32": return self.parse_decl()
        elif tok.kind == "identifier": return self.parse_assign()
        else: raise CompileError(f"line {tok.line}:{tok.col}: cannot start a statement with '{tok.text}'")

    def parse_decl(self):
        start = self.eat()
        mutable = False
        tok = self.peek()
        if tok is not None and tok.text == "mut":
            self.eat()
            mutable = True
        
        name = self.expect("identifier", "a variable name")
        
        tok = self.peek()
        if tok is None or tok.kind != "lbrace":
            line = tok.line if tok else (self.toks[-1].line if self.toks else 1)
            col = tok.col if tok else (self.toks[-1].col + len(self.toks[-1].text) if self.toks else 1)
            raise CompileError(f"line {line}:{col}: variable '{name.text}' needs an initialiser in {{}}")
        self.eat()
        
        init = self.parse_expr()
        
        tok = self.peek()
        if tok is None or tok.kind != "rbrace":
            line = tok.line if tok else (self.toks[-1].line if self.toks else 1)
            col = tok.col if tok else (self.toks[-1].col + len(self.toks[-1].text) if self.toks else 1)
            raise CompileError(f"line {line}:{col}: variable '{name.text}' needs an initialiser in {{}}")
        self.eat()
        
        return DeclNode(start.line, start.col, name.text, mutable, init)

    def parse_assign(self):
        name = self.expect("identifier", "a variable name")
        tok = self.peek()
        if tok is None or tok.text != ":=":
            line = tok.line if tok else name.line
            col = tok.col if tok else name.col + len(name.text)
            got = f"'{tok.text}'" if tok else "end of line"
            raise CompileError(f"line {line}:{col}: expected ':=' after '{name.text}', got {got}")
        self.eat()
        value = self.parse_expr()
        return AssignNode(name.line, name.col, name.text, value)

    def parse_exit(self):
        start = self.eat()
        value = self.parse_factor()
        return ExitNode(start.line, start.col, value)

    def parse_expr(self):
        node = self.parse_term()
        while (tok := self.peek()) is not None and tok.kind == "operator" and tok.text in ("+", "-"):
            self.eat()
            node = BinOpNode(tok.line, tok.col, tok.text, node, self.parse_term())
        return node

    def parse_term(self):
        node = self.parse_factor()
        while (tok := self.peek()) is not None and tok.kind == "operator" and tok.text == "*":
            self.eat()
            node = BinOpNode(tok.line, tok.col, tok.text, node, self.parse_factor())
        return node

    def parse_factor(self):
        tok = self.peek()
        if tok is None:
            last = self.toks[-1] if self.toks else Token("error", "", 1, 1)
            raise CompileError(f"line {last.line}:{last.col + len(last.text)}: expected a constant or a variable")
        
        if tok.kind == "constant":
            self.eat()
            return ConstNode(tok.line, tok.col, int(tok.text))
        elif tok.kind == "identifier":
            self.eat()
            return VarNode(tok.line, tok.col, tok.text)
        else:
            if tok.text == "}":
                raise CompileError(f"line {tok.line}:{tok.col}: expected a constant or a variable")
            
            raise CompileError(f"line {tok.line}:{tok.col}: expected a constant or a variable, got '{tok.text}'")

def main():
    args = sys.argv[1:]
    print_ast = False
    if "--ast" in args:
        print_ast = True
        args.remove("--ast")

    if print_ast:
        if len(args) != 1:
            print(f"usage: {sys.argv[0]} [--ast] input.txt", file=sys.stderr)
            sys.exit(1)
        input_path, output_path = args[0], None
    else:
        if len(args) != 2:
            print(f"usage: {sys.argv[0]} [--ast] input.txt output.ll", file=sys.stderr)
            sys.exit(1)
        input_path, output_path = args[0], args[1]

    module = ir.Module(name="practice3")
    module.triple = llvm.get_default_triple()
    main_function = ir.Function(module, ir.FunctionType(I32, []), name="main")
    builder = ir.IRBuilder(main_function.append_basic_block("entry"))
    printf = ir.Function(module, ir.FunctionType(I32, [ir.PointerType(I8)], var_arg=True), name="printf")
    text = b"Program exit with result %d\n\0"
    fmt_type = ir.ArrayType(I8, len(text))
    fmt = ir.GlobalVariable(module, fmt_type, name="fmt")
    fmt.linkage = "private"
    fmt.global_constant = True
    fmt.initializer = ir.Constant(fmt_type, bytearray(text))

    try:
        with open(input_path, "rb") as source: lines = lex(source.read())
        parser = Parser(lines)
        tree = parser.parse_program()
        if print_ast:
            tree.dump()
            sys.exit(0)
        symbols = {}
        tree.codegen(builder, symbols, printf, fmt)
        with open(output_path, "w") as output:
            output.write(str(module))
    except OSError as e:
        print(f"compilation error: {e}", file=sys.stderr)
        sys.exit(1)
    except CompileError as e:
        print(f"compilation error: {e}", file=sys.stderr)
        if output_path:
            import os
            try: os.remove(output_path)
            except OSError: pass
        sys.exit(1)

if __name__ == "__main__":
    main()
