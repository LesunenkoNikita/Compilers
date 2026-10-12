import sys
from llvmlite import ir
import llvmlite.binding as llvm

I64 = ir.IntType(64)
I32 = ir.IntType(32)
I8 = ir.IntType(8)
I1 = ir.IntType(1)

BUILTIN = ("i32", "i64", "bool")


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
    b"while": "keyword",
    b"struct": "keyword",
    b"fn": "keyword"
}


def is_alpha(b):
    return b is not None and (65 <= b <= 90 or 97 <= b <= 122 or b == 95)


def is_digit(b):
    return b is not None and 48 <= b <= 57


SINGLE = {
    ord("{"): "lbrace",
    ord("}"): "rbrace",
    ord(","): "comma",
    ord("."): "dot",
    ord("("): "lparen",
    ord(")"): "rparen"
}


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

            if b in SINGLE:
                tokens.append(Token(SINGLE[b], chr(b), line, col))
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

            if b == ord("-") and i + 1 < len(data) and data[i + 1] == ord(">"):
                tokens.append(Token("arrow", "->", line, col))
                i += 2
                col += 2
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


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def llvm_type(type_name, ctx):
    if type_name == "i64":
        return I64
    if type_name == "bool":
        return I1
    if type_name == "i32":
        return I32
    return ctx["struct_types"][type_name]


def coerce(builder, val, have, want):
    if have == "i32" and want == "i64":
        return builder.sext(val, I64, name="wide")
    return val


def field_ptr(builder, ptr, indices):
    for idx in indices:
        ptr = builder.gep(ptr, [ir.Constant(I32, 0), ir.Constant(I32, idx)], inbounds=True, name="field")
    return ptr


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


class FieldNode(ExprNode):
    def __init__(self, line, col, names):
        super().__init__(line, col)
        self.names = names

    def dump(self, indent=0):
        print(" " * indent + f"Field {'.'.join(t.text for t in self.names)}")

    def accept(self, visitor):
        return visitor.visit_field(self)

    def codegen(self, builder, ctx):
        ptr = field_ptr(builder, self.decl.storage, self.indices)
        return builder.load(ptr, name=f"{self.names[-1].text}_val")


class CallNode(ExprNode):
    def __init__(self, line, col, name, args):
        super().__init__(line, col)
        self.name = name
        self.args = args

    def dump(self, indent=0):
        print(" " * indent + f"Call {self.name}")
        for a in self.args:
            a.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_call(self)

    def codegen(self, builder, ctx):
        vals = []
        for arg, (p_type, _) in zip(self.args, self.fn.params):
            vals.append(coerce(builder, arg.codegen(builder, ctx), arg.type, p_type))
        return builder.call(self.fn.ir_func, vals, name=f"{self.name}_res")


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
        val = self.operand.codegen(builder, ctx)
        return builder.not_(val, name="nottmp")


class InitListNode(Node):
    def __init__(self, line, col, items):
        super().__init__(line, col)
        self.items = items

    def dump(self, indent=0):
        print(" " * indent + "InitList")
        for item in self.items:
            item.dump(indent + 2)


def gen_item(item, builder, ctx):
    if not isinstance(item, InitListNode):
        return coerce(builder, item.codegen(builder, ctx), item.type, item.target_type)
    if item.copy:
        return gen_item(item.items[0], builder, ctx)
    val = ir.Constant(llvm_type(item.type, ctx), ir.Undefined)
    for i, sub in enumerate(item.items):
        val = builder.insert_value(val, gen_item(sub, builder, ctx), i, name=f"{item.type}_init")
    return val


class DeclNode(StmtNode):
    def __init__(self, line, col, name, type_tok, mutable, inits, lbrace):
        super().__init__(line, col)
        self.name = name
        self.type_tok = type_tok
        self.type_name = type_tok.text if type_tok else None
        self.mutable = mutable
        self.inits = inits
        self.lbrace = lbrace
        self.copy = False

    def dump(self, indent=0):
        mut_str = 'mut' if self.mutable else 'const'
        print(" " * indent + f"Decl {self.name} {self.type_name} {mut_str}")
        for init in self.inits:
            init.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_decl(self)

    def codegen(self, builder, ctx):
        fn = builder.function
        entry_bb = fn.entry_basic_block
        curr_bb = builder.block

        builder.position_at_start(entry_bb)
        self.storage = builder.alloca(llvm_type(self.type_name, ctx), name=self.name)
        builder.position_at_end(curr_bb)

        if self.type_name in BUILTIN:
            init = self.inits[0]
            val = coerce(builder, init.codegen(builder, ctx), init.type, self.type_name)
            builder.store(val, self.storage)
        elif self.copy:
            builder.store(gen_item(self.inits[0], builder, ctx), self.storage)
        else:
            for i, item in enumerate(self.inits):
                val = gen_item(item, builder, ctx)
                builder.store(val, field_ptr(builder, self.storage, [i]))


class AssignNode(StmtNode):
    def __init__(self, line, col, names, value):
        super().__init__(line, col)
        self.names = names
        self.name = ".".join(t.text for t in names)
        self.value = value

    def dump(self, indent=0):
        print(" " * indent + f"Assign {self.name}")
        self.value.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_assign(self)

    def codegen(self, builder, ctx):
        ptr = field_ptr(builder, self.decl.storage, self.indices)
        val = coerce(builder, self.value.codegen(builder, ctx), self.value.type, self.target_type)
        builder.store(val, ptr)


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

        if self.ret_type is not None:
            builder.ret(coerce(builder, val, self.value.type, self.ret_type))
            return

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
        for s in self.statements:
            s.codegen(builder, ctx)
        if self.exit_node:
            self.exit_node.codegen(builder, ctx)


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
        cond_val = self.cond.codegen(builder, ctx)
        fn = builder.function

        then_bb = fn.append_basic_block("then")
        else_bb = fn.append_basic_block("else") if self.else_block else None
        merge_bb = fn.append_basic_block("merge")

        builder.cbranch(cond_val, then_bb, else_bb or merge_bb)

        builder.position_at_end(then_bb)
        self.then_block.codegen(builder, ctx)
        if not builder.block.is_terminated:
            builder.branch(merge_bb)

        if self.else_block:
            builder.position_at_end(else_bb)
            self.else_block.codegen(builder, ctx)
            if not builder.block.is_terminated:
                builder.branch(merge_bb)

        builder.position_at_end(merge_bb)


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
        fn = builder.function
        cond_bb = fn.append_basic_block("while_cond")
        body_bb = fn.append_basic_block("while_body")
        end_bb = fn.append_basic_block("while_end")

        builder.branch(cond_bb)

        builder.position_at_end(cond_bb)
        cond_val = self.cond.codegen(builder, ctx)
        builder.cbranch(cond_val, body_bb, end_bb)

        builder.position_at_end(body_bb)
        self.body_block.codegen(builder, ctx)
        if not builder.block.is_terminated:
            builder.branch(cond_bb)

        builder.position_at_end(end_bb)


class FieldDeclNode(Node):
    def __init__(self, line, col, type_tok, mutable, name):
        super().__init__(line, col)
        self.type_tok = type_tok
        self.type_name = type_tok.text
        self.mutable = mutable
        self.name = name

    def dump(self, indent=0):
        mut_str = 'mut' if self.mutable else 'const'
        print(" " * indent + f"FieldDecl {self.name} {self.type_name} {mut_str}")


class StructDefNode(Node):
    def __init__(self, line, col, name, fields):
        super().__init__(line, col)
        self.name = name
        self.fields = fields
        self.index = {}

    def dump(self, indent=0):
        print(" " * indent + f"Struct {self.name}")
        for f in self.fields:
            f.dump(indent + 2)


class FnDefNode(Node):
    def __init__(self, line, col, name, params, ret_tok, body):
        super().__init__(line, col)
        self.name = name
        self.params = [(t.text, n.text) for t, n in params]
        self.param_toks = params
        self.ret_tok = ret_tok
        self.ret_type = ret_tok.text
        self.body = body

    def dump(self, indent=0):
        print(" " * indent + f"Fn {self.name} -> {self.ret_type}")
        for p_type, p_name in self.params:
            print(" " * (indent + 2) + f"Param {p_name} {p_type}")
        self.body.dump(indent + 2)

    def declare(self, module, ctx):
        fn_type = ir.FunctionType(llvm_type(self.ret_type, ctx), [llvm_type(t, ctx) for t, _ in self.params])
        self.ir_func = ir.Function(module, fn_type, name=f"fn_{self.name}")

    def codegen(self, ctx):
        builder = ir.IRBuilder(self.ir_func.append_basic_block("entry"))
        for arg, decl in zip(self.ir_func.args, self.param_decls):
            arg.name = decl.name
            decl.storage = builder.alloca(arg.type, name=f"{decl.name}_slot")
            builder.store(arg, decl.storage)
        self.body.codegen(builder, ctx)


class ProgramNode(Node):
    def __init__(self, line, col, structs, fns, stmts, exit_node):
        super().__init__(line, col)
        self.structs = structs
        self.fns = fns
        self.stmts = stmts
        self.exit_node = exit_node

    def dump(self, indent=0):
        print(" " * indent + "Program")
        for s in self.structs:
            s.dump(indent + 2)
        for f in self.fns:
            f.dump(indent + 2)
        for s in self.stmts:
            s.dump(indent + 2)
        self.exit_node.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_program(self)

    def codegen(self, builder, ctx):
        module = builder.module
        ctx["struct_types"] = {}
        for s in self.structs:
            stype = module.context.get_identified_type(s.name)
            stype.set_body(*[llvm_type(f.type_name, ctx) for f in s.fields])
            ctx["struct_types"][s.name] = stype

        for f in self.fns:
            f.declare(module, ctx)
        for f in self.fns:
            f.codegen(ctx)

        for s in self.stmts:
            s.codegen(builder, ctx)
        self.exit_node.codegen(builder, ctx)


class Parser:
    def __init__(self, lines):
        self.lines = lines
        self.lidx = 0
        self.tidx = 0

    def peek(self, ahead=0):
        if self.lidx < len(self.lines) and self.tidx + ahead < len(self.lines[self.lidx]):
            return self.lines[self.lidx][self.tidx + ahead]
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

    def eol_pos(self):
        last = self.lines[self.lidx][-1]
        return last.line, last.col + len(last.text)

    def expect(self, kind, what):
        tok = self.peek()
        if tok is None or tok.kind != kind:
            t = tok or self.lines[self.lidx][-1]
            col_offset = len(t.text) if not tok else 0
            raise CompileError(f"line {t.line}:{t.col + col_offset}: expected {what}")
        return self.eat()

    def expect_text(self, text, what):
        tok = self.peek()
        if tok is None:
            line, col = self.eol_pos()
            raise CompileError(f"line {line}:{col}: expected {what}, found end of line")
        if tok.text != text:
            raise CompileError(f"line {tok.line}:{tok.col}: expected {what}, got '{tok.text}'")
        return self.eat()

    def parse_type(self):
        tok = self.peek()
        if tok is None:
            line, col = self.eol_pos()
            raise CompileError(f"line {line}:{col}: expected a type, found end of line")
        if tok.text in BUILTIN or tok.kind == "identifier":
            return self.eat()
        raise CompileError(f"line {tok.line}:{tok.col}: expected a type, got '{tok.text}'")

    def expect_lbrace_line(self, after, prev_line):
        tok = self.peek()
        if not tok or tok.kind != "lbrace":
            line, col = (tok.line, tok.col) if tok else (prev_line + 1, 1)
            got_str = f"'{tok.text}'" if tok else "end of file"
            raise CompileError(f"line {line}:{col}: expected '{{' on its own line after {after}, got {got_str}")
        lbrace = self.eat()
        self.check_eol()
        self.next_line()
        return lbrace

    def parse_program(self):
        structs = []
        fns = []
        stmts = []
        exit_node = None
        phase = 0

        while self.lidx < len(self.lines):
            first = self.peek()

            if not first:
                self.next_line()
                continue

            if exit_node is not None:
                raise CompileError(f"line {first.line}:{first.col}: statement after 'exit'")

            if first.text == "struct":
                if phase > 0:
                    raise CompileError(f"line {first.line}:{first.col}: 'struct' after a function or a statement")
                structs.append(self.parse_struct())
            elif first.text == "fn":
                if phase > 1:
                    raise CompileError(f"line {first.line}:{first.col}: 'fn' after a statement")
                phase = 1
                fns.append(self.parse_fn())
            elif first.text == "exit":
                exit_node = self.parse_exit()
                self.check_eol()
                self.next_line()
            else:
                phase = 2
                stmts.append(self.parse_statement())

        if exit_node is None:
            raise CompileError("line 1:1: no exit statement")

        return ProgramNode(1, 1, structs, fns, stmts, exit_node)

    def parse_struct(self):
        start = self.eat()
        name = self.expect("identifier", "a struct name")
        self.check_eol()
        self.next_line()

        lbrace = self.expect_lbrace_line(f"'struct {name.text}'", name.line)

        fields = []
        while self.lidx < len(self.lines):
            tok = self.peek()
            if tok.kind == "rbrace":
                self.eat()
                self.check_eol()
                self.next_line()
                if not fields:
                    raise CompileError(f"line {tok.line}:{tok.col}: struct '{name.text}' has no fields")
                return StructDefNode(start.line, start.col, name.text, fields)

            type_tok = self.parse_type()
            mutable = False
            if self.peek() and self.peek().text == "mut":
                self.eat()
                mutable = True
            fname = self.expect("identifier", "a field name")
            self.check_eol()
            self.next_line()
            fields.append(FieldDeclNode(fname.line, fname.col, type_tok, mutable, fname.text))

        raise CompileError(f"line {lbrace.line}:{lbrace.col}: '{{' is never closed")

    def parse_fn(self):
        start = self.eat()
        name = self.expect("identifier", "a function name")
        self.expect_text(":=", f"':=' after 'fn {name.text}'")
        self.expect_text("(", "'(' before the parameters")

        params = []
        if self.peek() and self.peek().kind == "rparen":
            self.eat()
        else:
            while True:
                p_type = self.parse_type()
                p_name = self.expect("identifier", "a parameter name")
                params.append((p_type, p_name))
                tok = self.peek()
                if tok and tok.kind == "comma":
                    self.eat()
                    continue
                self.expect_text(")", "',' or ')' after a parameter")
                break

        self.expect_text("->", "'->' before the result type")
        ret_tok = self.parse_type()
        self.check_eol()
        self.next_line()

        lbrace = self.expect_lbrace_line(f"'fn {name.text}'", ret_tok.line)
        body = self.parse_block(lbrace)
        if body.exit_node is None:
            raise CompileError(f"line {body.end.line}:{body.end.col}: function '{name.text}' must end with 'exit'")
        return FnDefNode(start.line, start.col, name.text, params, ret_tok, body)

    def parse_statement(self):
        tok = self.peek()
        nxt = self.peek(1)
        if tok.text in BUILTIN or (tok.kind == "identifier" and nxt and (nxt.kind == "identifier" or nxt.text == "mut")):
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
        elif tok.text == "struct":
            raise CompileError(f"line {tok.line}:{tok.col}: cannot declare a struct inside a block")
        elif tok.text == "fn":
            raise CompileError(f"line {tok.line}:{tok.col}: cannot declare a function inside a block")
        elif tok.kind == "identifier":
            if nxt and nxt.kind == "lparen":
                raise CompileError(f"line {tok.line}:{tok.col}: cannot start a statement with a call of '{tok.text}'")
            res = self.parse_assign()
            self.check_eol()
            self.next_line()
            return res
        elif tok.kind == "lbrace":
            raise CompileError(f"line {tok.line}:{tok.col}: unexpected '{{'")
        else:
            raise CompileError(f"line {tok.line}:{tok.col}: cannot start a statement with '{tok.text}'")

    def parse_block(self, start_tok):
        stmts = []
        exit_node = None

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
                block = BlockNode(start_tok.line, start_tok.col, stmts, exit_node)
                block.end = tok
                return block

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
            got_str = f"'{tok.text}'" if tok else "end of line"
            raise CompileError(f"line {t.line}:{t.col}: expected '{{' on its own line after 'if', got {got_str}")

        lbrace = self.eat()
        self.check_eol()
        self.next_line()

        then_block = self.parse_block(lbrace)
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

            else_lbrace = self.eat()
            self.check_eol()
            self.next_line()

            else_block = self.parse_block(else_lbrace)

        return IfNode(start.line, start.col, cond, then_block, else_block)

    def parse_while(self):
        start = self.eat()
        cond = self.parse_expr()
        self.check_eol()
        self.next_line()

        tok = self.peek()
        if not tok or tok.kind != "lbrace":
            t = tok or Token("", "end of line", self.lines[-1][-1].line + 1, 1)
            got_str = f"'{tok.text}'" if tok else "end of line"
            raise CompileError(f"line {t.line}:{t.col}: expected '{{' on its own line after 'while', got {got_str}")

        lbrace = self.eat()
        self.check_eol()
        self.next_line()

        body_block = self.parse_block(lbrace)
        return WhileNode(start.line, start.col, cond, body_block)

    def parse_item(self):
        tok = self.peek()
        if tok and tok.kind == "lbrace":
            return self.parse_init_list()
        return self.parse_expr()

    def parse_init_list(self):
        lbrace = self.eat()
        if self.peek() and self.peek().kind == "rbrace":
            self.eat()
            return InitListNode(lbrace.line, lbrace.col, [])

        items = [self.parse_item()]
        while self.peek() and self.peek().kind == "comma":
            self.eat()
            items.append(self.parse_item())

        tok = self.peek()
        if not tok:
            line, col = self.eol_pos()
            raise CompileError(f"line {line}:{col}: expected '}}', found end of line")
        if tok.kind != "rbrace":
            raise CompileError(f"line {tok.line}:{tok.col}: expected ',' or '}}', got '{tok.text}'")
        self.eat()
        return InitListNode(lbrace.line, lbrace.col, items)

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
            t = tok or name
            col_offset = len(t.text) if not tok else 0
            raise CompileError(f"line {t.line}:{t.col + col_offset}: variable '{name.text}' needs an initialiser in {{}}")
        lbrace = self.eat()

        builtin = type_tok.text in BUILTIN
        if builtin:
            inits = [self.parse_expr()]
        else:
            inits = [] if self.peek() and self.peek().kind == "rbrace" else [self.parse_item()]

        while inits and self.peek() and self.peek().kind == "comma":
            self.eat()
            inits.append(self.parse_expr() if builtin else self.parse_item())

        tok = self.peek()
        if not tok or tok.kind != "rbrace":
            t = tok or self.lines[self.lidx][-1]
            if not tok:
                raise CompileError(f"line {t.line}:{t.col + len(t.text)}: expected '}}', found end of line")
            if not builtin:
                raise CompileError(f"line {t.line}:{t.col}: expected ',' or '}}', got '{t.text}'")
            raise CompileError(f"line {t.line}:{t.col}: variable '{name.text}' needs an initialiser in {{}}")
        self.eat()

        return DeclNode(name.line, name.col, name.text, type_tok, mutable, inits, lbrace)

    def parse_chain_rest(self, first):
        names = [first]
        while self.peek() and self.peek().kind == "dot":
            self.eat()
            names.append(self.expect("identifier", "a field name after '.'"))
        return names

    def parse_assign(self):
        name = self.expect("identifier", "a variable name")
        names = self.parse_chain_rest(name)
        last = names[-1]
        tok = self.peek()

        if tok is None or tok.text != ":=":
            t = tok or last
            col_offset = len(t.text) if not tok else 0
            got_str = 'end of line' if not tok else repr(tok.text)
            raise CompileError(f"line {t.line}:{t.col + col_offset}: expected ':=' after '{last.text}', got {got_str}")

        self.eat()
        return AssignNode(name.line, name.col, names, self.parse_expr())

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

    def parse_call(self, name):
        self.eat()
        args = []
        if self.peek() and self.peek().kind == "rparen":
            self.eat()
            return CallNode(name.line, name.col, name.text, args)

        while True:
            args.append(self.parse_expr())
            tok = self.peek()
            if tok is None:
                line, col = self.eol_pos()
                raise CompileError(f"line {line}:{col}: expected ')', found end of line")
            if tok.kind == "comma":
                self.eat()
                continue
            if tok.kind == "rparen":
                self.eat()
                return CallNode(name.line, name.col, name.text, args)
            raise CompileError(f"line {tok.line}:{tok.col}: expected ',' or ')', got '{tok.text}'")

    def parse_factor(self):
        tok = self.peek()

        if tok is None:
            last = self.lines[self.lidx][-1]
            raise CompileError(f"line {last.line}:{last.col + len(last.text)}: expected a constant or a variable, found end of line")

        self.eat()

        if tok.text == "!":
            return NotNode(tok.line, tok.col, self.parse_factor())

        if tok.kind == "constant":
            return ConstNode(tok.line, tok.col, int(tok.text))
        elif tok.kind == "identifier":
            nxt = self.peek()
            if nxt and nxt.kind == "lparen":
                return self.parse_call(tok)
            if nxt and nxt.kind == "dot":
                return FieldNode(tok.line, tok.col, self.parse_chain_rest(tok))
            return VarNode(tok.line, tok.col, tok.text)
        elif tok.kind == "keyword" and tok.text in ("true", "false"):
            return BoolNode(tok.line, tok.col, tok.text == "true")

        raise CompileError(f"line {tok.line}:{tok.col}: expected a constant or a variable, got '{tok.text}'")


class SemanticChecker:
    def __init__(self):
        self.scopes = [{}]
        self.structs = {}
        self.functions = {}
        self.current_fn = None

    def lookup(self, node, name):
        for frame in reversed(self.scopes):
            if name in frame:
                return frame[name]
        raise CompileError(f"line {node.line}:{node.col}: variable '{name}' is used before its declaration")

    def check_type(self, tok):
        if tok.text not in BUILTIN and tok.text not in self.structs:
            raise CompileError(f"line {tok.line}:{tok.col}: type '{tok.text}' is used before its declaration")

    def check_assignable(self, expr, want, at, what):
        have = expr.type

        if isinstance(expr, ConstNode) and want == "i32" and have == "i64":
            raise CompileError(f"line {expr.line}:{expr.col}: constant {expr.value} does not fit in {want}")

        if have == want or (have == "i32" and want == "i64"):
            return

        raise CompileError(f"line {at.line}:{at.col}: cannot {what} of type {want} with a value of type {have}")

    def const_field(self, type_name):
        for f in self.structs[type_name].fields:
            if not f.mutable:
                return (type_name, f.name)
            if f.type_name in self.structs:
                inner = self.const_field(f.type_name)
                if inner:
                    return inner
        return None

    def resolve_chain(self, decl, names):
        curr_type = decl.type_name
        indices = []
        links = []
        for prev, tok in zip(names, names[1:]):
            if curr_type not in self.structs:
                raise CompileError(f"line {tok.line}:{tok.col}: cannot access field '{tok.text}': '{prev.text}' is not a struct, got {curr_type}")
            sdef = self.structs[curr_type]
            if tok.text not in sdef.index:
                raise CompileError(f"line {tok.line}:{tok.col}: struct '{curr_type}' has no field '{tok.text}'")
            idx = sdef.index[tok.text]
            field = sdef.fields[idx]
            indices.append(idx)
            links.append((tok, field))
            curr_type = field.type_name
        return curr_type, indices, links

    def visit_program(self, node):
        for s in node.structs:
            self.visit_struct_def(s)

        for f in node.fns:
            if f.name in self.functions:
                raise CompileError(f"line {f.line}:{f.col}: function '{f.name}' is already declared")
            for p_type, _ in f.param_toks:
                self.check_type(p_type)
            self.check_type(f.ret_tok)
            self.functions[f.name] = f

        for f in node.fns:
            self.visit_fn_def(f)

        for s in node.stmts:
            s.accept(self)
        node.exit_node.accept(self)

    def visit_struct_def(self, node):
        if node.name in self.structs:
            raise CompileError(f"line {node.line}:{node.col}: struct '{node.name}' is already declared")

        for i, f in enumerate(node.fields):
            if f.type_name == node.name:
                raise CompileError(f"line {f.type_tok.line}:{f.type_tok.col}: struct '{node.name}' cannot contain itself")
            self.check_type(f.type_tok)
            if f.name in node.index:
                raise CompileError(f"line {f.line}:{f.col}: field '{f.name}' is already declared in struct '{node.name}'")
            node.index[f.name] = i

        self.structs[node.name] = node

    def visit_fn_def(self, node):
        frame = {}
        node.param_decls = []
        for p_type, p_name in node.param_toks:
            if p_name.text in frame:
                raise CompileError(f"line {p_name.line}:{p_name.col}: parameter '{p_name.text}' is already declared in function '{node.name}'")
            decl = DeclNode(p_name.line, p_name.col, p_name.text, p_type, False, [], None)
            frame[p_name.text] = decl
            node.param_decls.append(decl)

        saved = self.scopes
        self.scopes = [frame]
        self.current_fn = node
        for s in node.body.statements:
            s.accept(self)
        node.body.exit_node.accept(self)
        self.scopes = saved
        self.current_fn = None

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
            raise CompileError(f"line {node.line}:{node.col}: the condition of 'if' must be bool, got {node.cond.type}")

        node.then_block.accept(self)
        if node.else_block:
            node.else_block.accept(self)

    def visit_while(self, node):
        node.cond.accept(self)
        if node.cond.type != "bool":
            raise CompileError(f"line {node.line}:{node.col}: the condition of 'while' must be bool, got {node.cond.type}")

        node.body_block.accept(self)

    def check_init(self, items, type_name, lbrace):
        sdef = self.structs[type_name]
        first = items[0] if items else None
        checked = False

        if len(items) == 1 and not isinstance(first, InitListNode):
            first.accept(self)
            checked = True
            if first.type == type_name:
                first.target_type = type_name
                return True

        if len(items) != len(sdef.fields):
            raise CompileError(f"line {lbrace.line}:{lbrace.col}: struct '{type_name}' needs {plural(len(sdef.fields), 'value')} in {{}}, got {len(items)}")

        for i, (item, field) in enumerate(zip(items, sdef.fields)):
            if isinstance(item, InitListNode):
                if field.type_name in BUILTIN:
                    raise CompileError(f"line {item.line}:{item.col}: cannot initialise field '{field.name}' of type {field.type_name} with {{}}")
                item.copy = self.check_init(item.items, field.type_name, item)
                item.type = field.type_name
                item.target_type = field.type_name
            else:
                if not (i == 0 and checked):
                    item.accept(self)
                self.check_assignable(item, field.type_name, item, f"initialise field '{field.name}'")
                item.target_type = field.type_name
        return False

    def visit_decl(self, node):
        self.check_type(node.type_tok)
        top_frame = self.scopes[-1]

        if node.name in top_frame:
            raise CompileError(f"line {node.line}:{node.col}: variable '{node.name}' is already declared in this block")

        if node.type_name in BUILTIN:
            if len(node.inits) != 1:
                raise CompileError(f"line {node.lbrace.line}:{node.lbrace.col}: variable '{node.name}' needs 1 value in {{}}, got {len(node.inits)}")
            node.inits[0].accept(self)
            self.check_assignable(node.inits[0], node.type_name, node, f"initialise '{node.name}'")
        else:
            node.copy = self.check_init(node.inits, node.type_name, node.lbrace)

        top_frame[node.name] = node

    def visit_assign(self, node):
        root = node.names[0]
        decl = self.lookup(node, root.text)

        if len(node.names) == 1:
            if not decl.mutable:
                raise CompileError(f"line {node.line}:{node.col}: cannot assign to '{node.name}': it is not mut")
            node.target_type = decl.type_name
            node.indices = []
        else:
            if not decl.mutable:
                raise CompileError(f"line {root.line}:{root.col}: cannot assign to '{node.name}': '{root.text}' is not mut")
            node.target_type, node.indices, links = self.resolve_chain(decl, node.names)
            for tok, field in links:
                if not field.mutable:
                    raise CompileError(f"line {tok.line}:{tok.col}: cannot assign to '{node.name}': field '{tok.text}' is not mut")

        if node.target_type in self.structs:
            bad = self.const_field(node.target_type)
            if bad:
                raise CompileError(f"line {node.line}:{node.col}: cannot assign to '{node.name}': field '{bad[1]}' of '{bad[0]}' is not mut")

        node.value.accept(self)
        self.check_assignable(node.value, node.target_type, node, f"assign to '{node.name}'")
        node.decl = decl

    def visit_exit(self, node):
        node.value.accept(self)
        have = node.value.type

        if self.current_fn is None:
            if have not in BUILTIN:
                raise CompileError(f"line {node.value.line}:{node.value.col}: the value of 'exit' at the top level must be i32, i64 or bool, got {have}")
            node.ret_type = None
            return

        want = self.current_fn.ret_type
        if isinstance(node.value, ConstNode) and want == "i32" and have == "i64":
            raise CompileError(f"line {node.value.line}:{node.value.col}: constant {node.value.value} does not fit in {want}")
        if not (have == want or (have == "i32" and want == "i64")):
            raise CompileError(f"line {node.value.line}:{node.value.col}: cannot exit from '{self.current_fn.name}' of type {want} with a value of type {have}")
        node.ret_type = want

    def visit_call(self, node):
        if node.name not in self.functions:
            raise CompileError(f"line {node.line}:{node.col}: function '{node.name}' is used before its declaration")

        fn = self.functions[node.name]
        if len(node.args) != len(fn.params):
            raise CompileError(f"line {node.line}:{node.col}: function '{node.name}' needs {plural(len(fn.params), 'argument')}, got {len(node.args)}")

        for arg, (p_type, p_name) in zip(node.args, fn.params):
            arg.accept(self)
            self.check_assignable(arg, p_type, arg, f"initialise parameter '{p_name}'")

        node.type = fn.ret_type
        node.fn = fn

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
            for t in (lt, rt):
                if t not in BUILTIN:
                    raise CompileError(f"line {node.line}:{node.col}: cannot apply '{node.op}' to {t}")

            node.type = "i64" if "i64" in (lt, rt) else "i32"
        else:
            if lt not in BUILTIN or rt not in BUILTIN:
                raise CompileError(f"line {node.line}:{node.col}: cannot compare {lt} with {rt}")
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

    def visit_field(self, node):
        node.decl = self.lookup(node, node.names[0].text)
        node.type, node.indices, _ = self.resolve_chain(node.decl, node.names)

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

    module = ir.Module(name="practice6")
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
