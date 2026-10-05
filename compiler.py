import sys
from llvmlite import ir
import llvmlite.binding as llvm

I64 = ir.IntType(64)
I32 = ir.IntType(32)
I8 = ir.IntType(8)
I1 = ir.IntType(1)


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
    b"false": "keyword",
    b"if": "keyword",
    b"else": "keyword",
    b"while": "keyword"
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

    while i <= len(data):
        b = data[i] if i < len(data) else None

        if state == "START":
            if b is None:
                break

            if b in (32, 9):
                i += 1
                col += 1
                continue

            if b == 10:
                if tokens:
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
                tokens.append(Token("lbrace", "{", line, col))
                i += 1
                col += 1
                continue

            if b == ord("}"):
                tokens.append(Token("rbrace", "}", line, col))
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
                tokens.append(Token("operator", "!", line, col))
                i += 1
                col += 1
                continue

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

    if tokens:
        lines.append(tokens)

    return lines


class Node:
    def __init__(self, line, col):
        self.line = line
        self.col = col

    def accept(self, visitor):
        pass


class ExprNode(Node):
    pass


class StmtNode(Node):
    pass


def coerce(builder, val, have, want):
    if have == "i32" and want == "i64":
        return builder.sext(val, I64, name="wide")
    return val


class ConstNode(ExprNode):
    def __init__(self, line, col, value):
        super().__init__(line, col)
        self.value = value

    def dump(self, indent=0):
        print(" " * indent + f"Const {self.value}")

    def accept(self, visitor):
        return visitor.visit_const(self)

    def codegen(self, builder, ctx):
        return ir.Constant(I64 if self.type == "i64" else I32, self.value)


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
        return ir.Constant(I1, 1 if self.value else 0)


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

        if self.op in ("+", "-", "*"):
            l = coerce(builder, l, self.left.type, self.type)
            r = coerce(builder, r, self.right.type, self.type)

            if self.op == "+":
                return builder.add(l, r, name="addtmp")
            if self.op == "-":
                return builder.sub(l, r, name="subtmp")
            if self.op == "*":
                return builder.mul(l, r, name="multmp")
        else:
            if self.left.type in ("i32", "i64"):
                w = "i64" if "i64" in (self.left.type, self.right.type) else "i32"
                l = coerce(builder, l, self.left.type, w)
                r = coerce(builder, r, self.right.type, w)

            return builder.icmp_signed(self.op, l, r)


class NotNode(ExprNode):
    def __init__(self, line, col, operand):
        super().__init__(line, col)
        self.operand = operand

    def dump(self, indent=0):
        print(" " * indent + "Not")
        self.operand.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_not(self)

    def codegen(self, builder, ctx):
        pass


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
        if self.type_name == "i64":
            t = I64
        elif self.type_name == "bool":
            t = I1
        else:
            t = I32

        self.storage = builder.alloca(t, name=self.name)
        val = coerce(builder, self.init.codegen(builder, ctx), self.init.type, self.type_name)
        builder.store(val, self.storage)


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
        val = coerce(builder, self.value.codegen(builder, ctx), self.value.type, self.decl.type_name)
        builder.store(val, self.decl.storage)


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

        if self.value.type in ("i32", "i64"):
            val = coerce(builder, val, self.value.type, "i64")
            fmt_ptr = builder.bitcast(ctx["fmt_int"], ir.PointerType(I8))
            builder.call(ctx["printf"], [fmt_ptr, val])
        else:
            str_true_ptr = builder.bitcast(ctx["str_true"], ir.PointerType(I8))
            str_false_ptr = builder.bitcast(ctx["str_false"], ir.PointerType(I8))
            s_ptr = builder.select(val, str_true_ptr, str_false_ptr)
            fmt_ptr = builder.bitcast(ctx["fmt_str"], ir.PointerType(I8))
            builder.call(ctx["printf"], [fmt_ptr, s_ptr])

        builder.ret(ir.Constant(I32, 0))


class BlockNode(Node):
    def __init__(self, line, col, statements, exit_node):
        super().__init__(line, col)
        self.statements = statements
        self.exit_node = exit_node

    def dump(self, indent=0):
        print(" " * indent + "Block")
        for s in self.statements:
            s.dump(indent + 2)
        if self.exit_node:
            self.exit_node.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_block(self)

    def codegen(self, builder, ctx):
        pass


class IfNode(StmtNode):
    def __init__(self, line, col, cond, then_block, else_block):
        super().__init__(line, col)
        self.cond = cond
        self.then_block = then_block
        self.else_block = else_block

    def dump(self, indent=0):
        print(" " * indent + "If")
        self.cond.dump(indent + 2)
        self.then_block.dump(indent + 2)
        if self.else_block:
            self.else_block.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_if(self)

    def codegen(self, builder, ctx):
        pass


class WhileNode(StmtNode):
    def __init__(self, line, col, cond, body_block):
        super().__init__(line, col)
        self.cond = cond
        self.body_block = body_block

    def dump(self, indent=0):
        print(" " * indent + "While")
        self.cond.dump(indent + 2)
        self.body_block.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_while(self)

    def codegen(self, builder, ctx):
        pass


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
        self.lidx = 0
        self.tidx = 0

    def peek(self):
        if self.lidx < len(self.lines) and self.tidx < len(self.lines[self.lidx]):
            return self.lines[self.lidx][self.tidx]
        return None

    def eat(self):
        tok = self.lines[self.lidx][self.tidx]
        self.tidx += 1
        return tok

    def check_eol(self):
        if self.tidx < len(self.lines[self.lidx]):
            t = self.peek()
            raise CompileError(f"line {t.line}:{t.col}: unexpected '{t.text}' after the statement")

    def next_line(self):
        self.lidx += 1
        self.tidx = 0

    def expect(self, kind, what):
        tok = self.peek()
        if tok is None or tok.kind != kind:
            t = tok or (self.lines[-1][-1] if self.lines and self.lines[-1] else Token("", "", 1, 1))
            col_offset = len(t.text) if not tok else 0
            raise CompileError(f"line {t.line}:{t.col + col_offset}: expected {what}")
        return self.eat()

    def parse_program(self):
        stmts = []
        exit_node = None

        while self.lidx < len(self.lines):
            first = self.peek()
            
            if not first:
                self.next_line()
                continue
                
            if first.text == "exit":
                if exit_node is not None:
                    raise CompileError(f"line {first.line}:{first.col}: statement after 'exit'")
                exit_node = self.parse_exit()
                self.check_eol()
                self.next_line()
            else:
                if exit_node is not None:
                    raise CompileError(f"line {first.line}:{first.col}: statement after 'exit'")
                stmts.append(self.parse_statement())

        if exit_node is None:
            raise CompileError("line 1:1: no exit statement")

        return ProgramNode(1, 1, stmts, exit_node)

    def parse_statement(self):
        tok = self.peek()
        if tok.text in ("i32", "i64", "bool"):
            res = self.parse_decl()
            self.check_eol()
            self.next_line()
            return res
        elif tok.text == "if":
            return self.parse_if()
        elif tok.text == "while":
            return self.parse_while()
        elif tok.text == "else":
            raise CompileError(f"line {tok.line}:{tok.col}: 'else' without an 'if'")
        elif tok.kind == "identifier":
            res = self.parse_assign()
            self.check_eol()
            self.next_line()
            return res
        elif tok.kind == "lbrace":
            raise CompileError(f"line {tok.line}:{tok.col}: unexpected '{{'")
        else:
            raise CompileError(f"line {tok.line}:{tok.col}: cannot start a statement with '{tok.text}'")

    def parse_block(self):
        stmts = []
        exit_node = None
        start_tok = self.peek()

        while self.lidx < len(self.lines):
            tok = self.peek()
            
            if not tok:
                self.next_line()
                continue
                
            if tok.kind == "rbrace":
                self.eat()
                self.check_eol()
                self.next_line()
                if not stmts and not exit_node:
                    raise CompileError(f"line {start_tok.line}:{start_tok.col}: empty block")
                return BlockNode(start_tok.line, start_tok.col, stmts, exit_node)
                
            if exit_node is not None:
                raise CompileError(f"line {tok.line}:{tok.col}: statement after 'exit' in the same block")
                
            if tok.text == "exit":
                exit_node = self.parse_exit()
                self.check_eol()
                self.next_line()
            else:
                stmts.append(self.parse_statement())

        raise CompileError(f"line {start_tok.line}:{start_tok.col}: '{{' is never closed")

    def parse_if(self):
        start = self.eat()
        cond = self.parse_expr()
        self.check_eol()
        self.next_line()

        tok = self.peek()
        if not tok or tok.kind != "lbrace":
            t = tok or Token("", "end of line", self.lines[-1][-1].line + 1, 1)
            raise CompileError(f"line {t.line}:{t.col}: expected '{{' on its own line after 'if', got '{t.text}'")
            
        self.eat()
        self.check_eol()
        self.next_line()

        then_block = self.parse_block()
        else_block = None

        tok = self.peek()
        if tok and tok.text == "else":
            self.eat()
            self.check_eol()
            self.next_line()

            tok2 = self.peek()
            if not tok2 or tok2.kind != "lbrace":
                t2 = tok2 or Token("", "end of line", self.lines[-1][-1].line + 1, 1)
                raise CompileError(f"line {t2.line}:{t2.col}: expected '{{' on its own line after 'else'")
                
            self.eat()
            self.check_eol()
            self.next_line()

            else_block = self.parse_block()

        return IfNode(start.line, start.col, cond, then_block, else_block)

    def parse_while(self):
        start = self.eat()
        cond = self.parse_expr()
        self.check_eol()
        self.next_line()

        tok = self.peek()
        if not tok or tok.kind != "lbrace":
            t = tok or Token("", "end of line", self.lines[-1][-1].line + 1, 1)
            raise CompileError(f"line {t.line}:{t.col}: expected '{{' on its own line after 'while', got '{t.text}'")
            
        self.eat()
        self.check_eol()
        self.next_line()

        body_block = self.parse_block()
        return WhileNode(start.line, start.col, cond, body_block)

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
            t = tok or (self.lines[-1][-1] if self.lines and self.lines[-1] else Token("", "", 1, 1))
            col_offset = len(t.text) if not tok else 0
            raise CompileError(f"line {t.line}:{t.col + col_offset}: variable '{name.text}' needs an initialiser in {{}}")
        self.eat()
        
        init = self.parse_expr()
        
        tok = self.peek()
        if not tok or tok.kind != "rbrace":
            t = tok or (self.lines[-1][-1] if self.lines and self.lines[-1] else Token("", "", 1, 1))
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
            last = self.lines[-1][-1]
            raise CompileError(f"line {last.line}:{last.col + len(last.text)}: expected a constant or a variable, found end of line")
            
        self.eat()
        
        if tok.text == "!":
            return NotNode(tok.line, tok.col, self.parse_factor())
            
        if tok.kind == "constant":
            return ConstNode(tok.line, tok.col, int(tok.text))
        elif tok.kind == "identifier":
            return VarNode(tok.line, tok.col, tok.text)
        elif tok.kind == "keyword" and tok.text in ("true", "false"):
            return BoolNode(tok.line, tok.col, tok.text == "true")
            
        raise CompileError(f"line {tok.line}:{tok.col}: expected a constant or a variable, got '{tok.text}'")


class SemanticChecker:
    def __init__(self):
        self.scopes = [{}]

    def lookup(self, node, name):
        for frame in reversed(self.scopes):
            if name in frame:
                return frame[name]
        raise CompileError(f"line {node.line}:{node.col}: variable '{name}' is used before its declaration")

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

    def visit_block(self, node):
        self.scopes.append({})
        for s in node.statements:
            s.accept(self)
        if node.exit_node:
            node.exit_node.accept(self)
        self.scopes.pop()

    def visit_if(self, node):
        node.cond.accept(self)
        if node.cond.type != "bool":
            raise CompileError(f"line {node.cond.line}:{node.cond.col}: the condition of 'if' must be bool, got {node.cond.type}")
            
        node.then_block.accept(self)
        if node.else_block:
            node.else_block.accept(self)

    def visit_while(self, node):
        node.cond.accept(self)
        if node.cond.type != "bool":
            raise CompileError(f"line {node.cond.line}:{node.cond.col}: the condition of 'while' must be bool, got {node.cond.type}")
            
        node.body_block.accept(self)

    def visit_decl(self, node):
        top_frame = self.scopes[-1]
        
        if node.name in top_frame:
            raise CompileError(f"line {node.line}:{node.col}: variable '{node.name}' is already declared in this block")
            
        node.init.accept(self)
        self.check_assignable(node.init, node.type_name, node, f"initialise '{node.name}'")
        top_frame[node.name] = node

    def visit_assign(self, node):
        decl = self.lookup(node, node.name)
        
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

    def visit_not(self, node):
        node.operand.accept(self)
        if node.operand.type != "bool":
            raise CompileError(f"line {node.line}:{node.col}: cannot apply '!' to {node.operand.type}")
        node.type = "bool"

    def visit_const(self, node):
        if node.value <= 2147483647:
            node.type = "i32"
        elif node.value <= 9223372036854775807:
            node.type = "i64"
        else:
            raise CompileError(f"line {node.line}:{node.col}: constant {node.value} does not fit in i64")

    def visit_var(self, node):
        node.decl = self.lookup(node, node.name)
        node.type = node.decl.type_name

    def visit_bool(self, node):
        node.type = "bool"


def build_global_str(module, name, text):
    b = text.encode("ascii") + b"\0"
    g = ir.GlobalVariable(module, ir.ArrayType(I8, len(b)), name=name)
    g.linkage = "private"
    g.global_constant = True
    g.initializer = ir.Constant(ir.ArrayType(I8, len(b)), bytearray(b))
    return g


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
        input_path = args[0]
        output_path = None
    else:
        if len(args) != 2:
            print(f"usage: {sys.argv[0]} [--ast] input.txt output.ll", file=sys.stderr)
            sys.exit(1)
        input_path = args[0]
        output_path = args[1]
    
    module = ir.Module(name="practice5")
    module.triple = llvm.get_default_triple()
    
    main_func_type = ir.FunctionType(I32, [])
    main_function = ir.Function(module, main_func_type, name="main")
    builder = ir.IRBuilder(main_function.append_basic_block("entry"))
    
    printf_type = ir.FunctionType(I32, [ir.PointerType(I8)], var_arg=True)
    printf = ir.Function(module, printf_type, name="printf")
    
    ctx = {
        "printf": printf,
        "fmt_int": build_global_str(module, "fmt_int", "Program exit with result %lld\n"),
        "fmt_str": build_global_str(module, "fmt_str", "Program exit with result %s\n"),
        "str_true": build_global_str(module, "str_true", "true"),
        "str_false": build_global_str(module, "str_false", "false")
    }

    try:
        with open(input_path, "rb") as source:
            lines = lex(source.read())

        parser = Parser(lines)
        tree = parser.parse_program()

        if print_ast:
            tree.dump()
            sys.exit(0)

        checker = SemanticChecker()
        tree.accept(checker)

        tree.codegen(builder, ctx)
        
        if output_path:
            with open(output_path, "w") as out:
                out.write(str(module))

    except CompileError as e:
        print(f"compilation error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
