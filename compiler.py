import sys
from llvmlite import ir
import llvmlite.binding as llvm

I64 = ir.IntType(64)
I32 = ir.IntType(32)
I8 = ir.IntType(8)
I1 = ir.IntType(1)

BUILTIN = ("i32", "i64", "bool")
RESERVED = ("read", "print")


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
    ord(")"): "rparen",
    ord("["): "lbracket",
    ord("]"): "rbracket"
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

            if b == ord('"'):
                j = i + 1
                while j < len(data) and data[j] not in (ord('"'), 10):
                    j += 1
                if j >= len(data) or data[j] == 10:
                    raise CompileError(f"line {line}:{col}: string literal is not closed on its line")
                tokens.append(Token("string", data[i + 1:j].decode("latin-1"), line, col))
                col += j + 1 - i
                i = j + 1
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


def entry_alloca(builder, ty, name):
    curr_bb = builder.block
    builder.position_at_start(builder.function.entry_basic_block)
    slot = builder.alloca(ty, name=name)
    builder.position_at_end(curr_bb)
    return slot


def cstr(builder, ctx, text):
    cache = ctx["strings"]
    if text not in cache:
        data = text.encode("latin-1") + b"\0"
        g = ir.GlobalVariable(ctx["module"], ir.ArrayType(I8, len(data)), name=f"str.{len(cache)}")
        g.linkage = "private"
        g.global_constant = True
        g.initializer = ir.Constant(ir.ArrayType(I8, len(data)), bytearray(data))
        cache[text] = g
    return builder.bitcast(cache[text], ir.PointerType(I8))


def emit_printf(builder, ctx, fmt, *args):
    builder.call(ctx["printf"], [cstr(builder, ctx, fmt), *args])


def bool_str(builder, ctx, val):
    return builder.select(val, cstr(builder, ctx, "true"), cstr(builder, ctx, "false"))


def is_addressable(expr):
    return isinstance(expr, (VarNode, FieldNode))


def address_of(expr, builder, ctx):
    if is_addressable(expr):
        return field_ptr(builder, expr.decl.storage, expr.indices)
    val = expr.codegen(builder, ctx)
    slot = entry_alloca(builder, val.type, "tmp")
    builder.store(val, slot)
    return slot


SCALAR_FMT = {"i32": "%d", "i64": "%lld", "bool": "%s"}


def print_struct(builder, ctx, ptr, type_name, last):
    sdef = ctx["struct_defs"][type_name]
    emit_printf(builder, ctx, f"{type_name}{{")
    for i, f in enumerate(sdef.fields):
        sep = "" if i == 0 else ", "
        fptr = field_ptr(builder, ptr, [i])
        if f.type_name in BUILTIN:
            val = builder.load(fptr, name=f"{f.name}_val")
            if f.type_name == "bool":
                val = bool_str(builder, ctx, val)
            emit_printf(builder, ctx, f"{sep}{f.name}: {SCALAR_FMT[f.type_name]}", val)
        else:
            emit_printf(builder, ctx, f"{sep}{f.name}: ")
            print_struct(builder, ctx, fptr, f.type_name, False)
    emit_printf(builder, ctx, "}\n" if last else "}")


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
        return builder.load(field_ptr(builder, self.decl.storage, self.indices), name=f"{self.name}_val")


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
        self.this_decl = None

    def dump(self, indent=0):
        print(" " * indent + f"Call {self.name}")
        for a in self.args:
            a.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_call(self)

    def codegen(self, builder, ctx):
        vals = [self.this_decl.storage] if self.this_decl is not None else []
        for arg, (p_type, _) in zip(self.args, self.fn.params):
            vals.append(coerce(builder, arg.codegen(builder, ctx), arg.type, p_type))
        return builder.call(self.fn.ir_func, vals, name=f"{self.name}_res")


class MemberCallNode(ExprNode):
    def __init__(self, line, col, obj, name, args):
        super().__init__(line, col)
        self.obj = obj
        self.name = name
        self.args = args

    def dump(self, indent=0):
        print(" " * indent + f"MemberCall {self.name}")
        self.obj.dump(indent + 2)
        for a in self.args:
            a.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_member_call(self)

    def codegen(self, builder, ctx):
        vals = [address_of(self.obj, builder, ctx)]
        for arg, (p_type, _) in zip(self.args, self.fn.params):
            vals.append(coerce(builder, arg.codegen(builder, ctx), arg.type, p_type))
        return builder.call(self.fn.ir_func, vals, name=f"{self.name}.ret")


class CallableCallNode(MemberCallNode):
    def dump(self, indent=0):
        print(" " * indent + f"CallableCall {self.label}")
        for a in self.args:
            a.dump(indent + 2)


class ResultFieldNode(ExprNode):
    def __init__(self, line, col, obj, names):
        super().__init__(line, col)
        self.obj = obj
        self.names = names

    def dump(self, indent=0):
        print(" " * indent + f"ResultField {'.'.join(t.text for t in self.names)}")
        self.obj.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_result_field(self)

    def codegen(self, builder, ctx):
        val = self.obj.codegen(builder, ctx)
        return builder.extract_value(val, self.indices, name=f"{self.names[-1].text}_val")


class ReadNode(ExprNode):
    def dump(self, indent=0):
        print(" " * indent + "Read")

    def accept(self, visitor):
        return visitor.visit_read(self)

    def codegen(self, builder, ctx):
        slot = entry_alloca(builder, I32, "read_slot")
        builder.store(ir.Constant(I32, 0), slot)
        builder.call(ctx["scanf"], [cstr(builder, ctx, "%d"), slot])
        return builder.load(slot, name="read_val")


class StringNode(ExprNode):
    def __init__(self, line, col, text):
        super().__init__(line, col)
        self.text = text

    def dump(self, indent=0):
        print(" " * indent + f'String "{self.text}"')

    def accept(self, visitor):
        self.type = "string"


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


class PrintNode(StmtNode):
    def __init__(self, line, col, value):
        super().__init__(line, col)
        self.value = value

    def dump(self, indent=0):
        print(" " * indent + "Print")
        self.value.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_print(self)

    def codegen(self, builder, ctx):
        t = self.value.type
        if t == "string":
            emit_printf(builder, ctx, "%s\n", cstr(builder, ctx, self.value.text))
        elif t in BUILTIN:
            val = self.value.codegen(builder, ctx)
            if t == "bool":
                val = bool_str(builder, ctx, val)
            emit_printf(builder, ctx, SCALAR_FMT[t] + "\n", val)
        else:
            print_struct(builder, ctx, address_of(self.value, builder, ctx), t, True)


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


class LambdaNode(StmtNode):
    def __init__(self, line, col, name_tok, captures, params, ret_tok, body):
        super().__init__(line, col)
        self.name_tok = name_tok
        self.name = name_tok.text
        self.captures = captures
        self.param_toks = params
        self.ret_tok = ret_tok
        self.body = body
        self.struct_def = None
        self.decl = None

    def dump(self, indent=0):
        print(" " * indent + f"Lambda {self.name} -> {self.ret_tok.text}")
        if self.struct_def is not None:
            self.struct_def.dump(indent + 2)
            self.decl.dump(indent + 2)
            return
        for tok, mutable in self.captures:
            print(" " * (indent + 2) + f"Capture {'mut ' if mutable else ''}{tok.text}")
        for p_type, p_name in self.param_toks:
            print(" " * (indent + 2) + f"Param {p_name.text} {p_type.text}")
        self.body.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_lambda(self)

    def codegen(self, builder, ctx):
        self.decl.codegen(builder, ctx)


class FieldDeclNode(Node):
    def __init__(self, line, col, type_tok, mutable, name):
        super().__init__(line, col)
        self.type_tok = type_tok
        self.type_name = type_tok.text
        self.mutable = mutable
        self.name = name

    def dump(self, indent=0):
        mut_str = 'mut' if self.mutable else 'const'
        print(" " * indent + f"Member {self.name} {self.type_name} {mut_str}")


class StructDefNode(Node):
    def __init__(self, line, col, name, fields, methods):
        super().__init__(line, col)
        self.name = name
        self.fields = fields
        self.methods = methods
        self.index = {}
        self.method_index = {}

    def dump(self, indent=0):
        print(" " * indent + f"Struct {self.name}")
        for f in self.fields:
            f.dump(indent + 2)
        for m in self.methods:
            m.dump(indent + 2)


class ThisDecl:
    def __init__(self, struct):
        self.name = "this"
        self.type_name = struct.name
        self.mutable = True
        self.storage = None


class FnDefNode(Node):
    kind = "Fn"

    def __init__(self, line, col, name_tok, params, ret_tok, body):
        super().__init__(line, col)
        self.name_tok = name_tok
        self.name = name_tok.text
        self.params = [(t.text, n.text) for t, n in params]
        self.param_toks = params
        self.ret_tok = ret_tok
        self.ret_type = ret_tok.text
        self.body = body
        self.mutating = False
        self.calls_on_this = []

    def dump(self, indent=0):
        print(" " * indent + f"{self.kind} {self.name} -> {self.ret_type}")
        for p_type, p_name in self.params:
            print(" " * (indent + 2) + f"Param {p_name} {p_type}")
        self.body.dump(indent + 2)

    def accept(self, visitor):
        return visitor.visit_fn_def(self)

    def declare(self, module, ctx):
        fn_type = ir.FunctionType(llvm_type(self.ret_type, ctx), [llvm_type(t, ctx) for t, _ in self.params])
        self.ir_func = ir.Function(module, fn_type, name=f"fn_{self.name}")

    def store_params(self, builder, args):
        for arg, decl in zip(args, self.param_decls):
            arg.name = decl.name
            decl.storage = builder.alloca(arg.type, name=f"{decl.name}_slot")
            builder.store(arg, decl.storage)

    def codegen(self, ctx):
        builder = ir.IRBuilder(self.ir_func.append_basic_block("entry"))
        self.store_params(builder, self.ir_func.args)
        self.body.codegen(builder, ctx)


class MemberFnNode(FnDefNode):
    kind = "MemberFn"

    def __init__(self, line, col, name_tok, params, ret_tok, body, owner):
        super().__init__(line, col, name_tok, params, ret_tok, body)
        self.owner = owner

    def accept(self, visitor):
        return visitor.visit_member_fn(self)

    def declare(self, module, ctx):
        this_type = ir.PointerType(ctx["struct_types"][self.owner])
        fn_type = ir.FunctionType(llvm_type(self.ret_type, ctx), [this_type] + [llvm_type(t, ctx) for t, _ in self.params])
        self.ir_func = ir.Function(module, fn_type, name=f"{self.owner}_{self.name}")

    def codegen(self, ctx):
        builder = ir.IRBuilder(self.ir_func.append_basic_block("entry"))
        this_arg = self.ir_func.args[0]
        this_arg.name = "this"
        self.this_decl.storage = this_arg
        self.store_params(builder, self.ir_func.args[1:])
        self.body.codegen(builder, ctx)


class ProgramNode(Node):
    def __init__(self, line, col, structs, fns, stmts, exit_node):
        super().__init__(line, col)
        self.structs = structs
        self.fns = fns
        self.stmts = stmts
        self.exit_node = exit_node
        self.lambda_structs = []

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
        ctx["struct_defs"] = {}
        all_structs = self.structs + self.lambda_structs
        for s in all_structs:
            stype = module.context.get_identified_type(s.name)
            stype.set_body(*[llvm_type(f.type_name, ctx) for f in s.fields])
            ctx["struct_types"][s.name] = stype
            ctx["struct_defs"][s.name] = s

        all_fns = [m for s in all_structs for m in s.methods] + self.fns
        for f in all_fns:
            f.declare(module, ctx)
        for f in all_fns:
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
            elif first.text == "fn" and self.is_lambda_start():
                phase = 2
                stmts.append(self.parse_lambda())
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
        methods = []
        while self.lidx < len(self.lines):
            tok = self.peek()
            if tok.kind == "rbrace":
                self.eat()
                self.check_eol()
                self.next_line()
                if not fields:
                    raise CompileError(f"line {tok.line}:{tok.col}: struct '{name.text}' has no fields")
                return StructDefNode(start.line, start.col, name.text, fields, methods)

            if tok.text == "fn":
                if not fields:
                    raise CompileError(f"line {tok.line}:{tok.col}: member function before the first field of struct '{name.text}'")
                methods.append(self.parse_fn(name.text))
                continue

            if methods:
                raise CompileError(f"line {tok.line}:{tok.col}: field after a member function in struct '{name.text}'")

            type_tok = self.parse_type()
            mutable = False
            if self.peek() and self.peek().text == "mut":
                self.eat()
                mutable = True
            fname = self.expect("identifier", "a field name")
            self.check_name(fname, "a field")
            self.check_eol()
            self.next_line()
            fields.append(FieldDeclNode(fname.line, fname.col, type_tok, mutable, fname.text))

        raise CompileError(f"line {lbrace.line}:{lbrace.col}: '{{' is never closed")

    def check_name(self, tok, what):
        if tok.text in RESERVED:
            raise CompileError(f"line {tok.line}:{tok.col}: '{tok.text}' is a reserved name and cannot be used as {what} name")

    def is_lambda_start(self):
        t1, t2, t3 = self.peek(1), self.peek(2), self.peek(3)
        return bool(t1 and t1.kind == "identifier" and t2 and t2.text == ":=" and t3 and t3.kind == "lbracket")

    def parse_params(self):
        self.expect_text("(", "'(' before the parameters")
        params = []
        if self.peek() and self.peek().kind == "rparen":
            self.eat()
            return params
        while True:
            p_type = self.parse_type()
            p_name = self.expect("identifier", "a parameter name")
            self.check_name(p_name, "a parameter")
            params.append((p_type, p_name))
            tok = self.peek()
            if tok and tok.kind == "comma":
                self.eat()
                continue
            self.expect_text(")", "',' or ')' after a parameter")
            return params

    def parse_signature_and_body(self, name):
        params = self.parse_params()
        self.expect_text("->", "'->' before the result type")
        ret_tok = self.parse_type()
        self.check_eol()
        self.next_line()

        lbrace = self.expect_lbrace_line(f"'fn {name.text}'", ret_tok.line)
        body = self.parse_block(lbrace)
        if body.exit_node is None:
            raise CompileError(f"line {body.end.line}:{body.end.col}: function '{name.text}' must end with 'exit'")
        return params, ret_tok, body

    def parse_captures(self):
        self.eat()
        captures = []
        if self.peek() and self.peek().kind == "rbracket":
            self.eat()
            return captures
        while True:
            mutable = False
            if self.peek() and self.peek().text == "mut":
                self.eat()
                mutable = True
            captures.append((self.expect("identifier", "a captured name"), mutable))
            tok = self.peek()
            if tok and tok.kind == "comma":
                self.eat()
                continue
            self.expect_text("]", "',' or ']' in the capture list")
            return captures

    def parse_lambda(self):
        start = self.eat()
        name = self.expect("identifier", "a lambda name")
        self.check_name(name, "a lambda")
        self.eat()
        captures = self.parse_captures()
        params, ret_tok, body = self.parse_signature_and_body(name)
        return LambdaNode(start.line, start.col, name, captures, params, ret_tok, body)

    def parse_fn(self, owner=None):
        start = self.eat()
        name = self.expect("identifier", "a function name")
        self.check_name(name, "a member function" if owner else "a function")
        self.expect_text(":=", f"':=' after 'fn {name.text}'")
        tok = self.peek()
        if owner and tok and tok.kind == "lbracket":
            raise CompileError(f"line {tok.line}:{tok.col}: member function '{name.text}' cannot have a capture list")
        params, ret_tok, body = self.parse_signature_and_body(name)
        if owner:
            return MemberFnNode(start.line, start.col, name, params, ret_tok, body, owner)
        return FnDefNode(start.line, start.col, name, params, ret_tok, body)

    def find_call_in_statement(self):
        line = self.lines[self.lidx]
        for i in range(self.tidx, len(line)):
            t = line[i]
            if t.text == ":=":
                return None, False
            if t.kind == "lparen" and i > self.tidx and line[i - 1].kind == "identifier":
                assigns = any(x.text == ":=" for x in line[i:])
                return line[i - 1], assigns
        return None, False

    def parse_print(self):
        start = self.eat()
        self.expect_text("(", "'(' after 'print'")
        args = []
        if self.peek() and self.peek().kind == "rparen":
            self.eat()
        else:
            while True:
                tok = self.peek()
                after = self.peek(1)
                if tok and tok.kind == "string" and after and after.kind in ("comma", "rparen"):
                    self.eat()
                    args.append(StringNode(tok.line, tok.col, tok.text))
                else:
                    args.append(self.parse_expr())
                tok = self.peek()
                if tok and tok.kind == "comma":
                    self.eat()
                    continue
                self.expect_text(")", "',' or ')' in 'print'")
                break
        if len(args) != 1:
            raise CompileError(f"line {start.line}:{start.col}: 'print' needs 1 argument, got {len(args)}")
        return PrintNode(start.line, start.col, args[0])

    def parse_statement(self):
        tok = self.peek()
        nxt = self.peek(1)
        if tok.text == "print":
            res = self.parse_print()
            self.check_eol()
            self.next_line()
            return res
        if tok.kind == "identifier" and not (nxt and (nxt.kind == "identifier" or nxt.text == "mut")):
            call_tok, assigns = self.find_call_in_statement()
            if call_tok is not None:
                if assigns:
                    raise CompileError(f"line {call_tok.line}:{call_tok.col}: cannot assign to the result of a call of '{call_tok.text}'")
                raise CompileError(f"line {call_tok.line}:{call_tok.col}: cannot start a statement with a call of '{call_tok.text}'")
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
        elif tok.text == "fn" and self.is_lambda_start():
            return self.parse_lambda()
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
        self.check_name(name, "a variable")

        tok = self.peek()
        if not tok or tok.kind != "lbrace":
            t = tok or name
            raise CompileError(f"line {t.line}:{t.col}: variable '{name.text}' needs an initialiser in {{}}")
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
        self.check_name(name, "a variable")
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

    def parse_args(self):
        self.eat()
        args = []
        if self.peek() and self.peek().kind == "rparen":
            self.eat()
            return args

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
                return args
            raise CompileError(f"line {tok.line}:{tok.col}: expected ',' or ')', got '{tok.text}'")

    def parse_member_call(self, obj, name):
        self.check_name(name, "a member function")
        return MemberCallNode(name.line, name.col, obj, name.text, self.parse_args())

    def parse_chain(self, first):
        names = [first]
        while True:
            nxt = self.peek()
            if nxt and nxt.kind == "lparen":
                if len(names) == 1:
                    return CallNode(first.line, first.col, first.text, self.parse_args())
                obj = VarNode(first.line, first.col, first.text) if len(names) == 2 else FieldNode(first.line, first.col, names[:-1])
                return self.parse_member_call(obj, names[-1])
            if nxt and nxt.kind == "dot":
                self.eat()
                names.append(self.expect("identifier", "a field name after '.'"))
                continue
            if len(names) == 1:
                return VarNode(first.line, first.col, first.text)
            return FieldNode(first.line, first.col, names)

    def parse_after_call(self, node):
        while self.peek() and self.peek().kind == "dot":
            dot = self.eat()
            name = self.expect("identifier", "a field name after '.'")
            nxt = self.peek()
            if nxt and nxt.kind == "lparen":
                node = self.parse_member_call(node, name)
            elif isinstance(node, ResultFieldNode):
                node.names.append(name)
                node.dots.append(dot)
            else:
                node = ResultFieldNode(dot.line, dot.col, node, [name])
                node.dots = [dot]
        return node

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
        elif tok.kind == "string":
            raise CompileError(f"line {tok.line}:{tok.col}: a string literal can only be the argument of 'print'")
        elif tok.text == "print":
            raise CompileError(f"line {tok.line}:{tok.col}: 'print' has no value, it can only be a statement")
        elif tok.text == "read":
            nxt = self.peek()
            if not nxt or nxt.kind != "lparen":
                raise CompileError(f"line {tok.line}:{tok.col}: 'read' is a reserved name, it can only be called as read()")
            args = self.parse_args()
            if args:
                raise CompileError(f"line {tok.line}:{tok.col}: 'read' needs 0 arguments, got {len(args)}")
            return self.parse_after_call(ReadNode(tok.line, tok.col))
        elif tok.kind == "identifier":
            node = self.parse_chain(tok)
            if isinstance(node, (CallNode, MemberCallNode)):
                node = self.parse_after_call(node)
            return node
        elif tok.kind == "keyword" and tok.text in ("true", "false"):
            return BoolNode(tok.line, tok.col, tok.text == "true")

        raise CompileError(f"line {tok.line}:{tok.col}: expected a constant or a variable, got '{tok.text}'")


class SemanticChecker:
    def __init__(self):
        self.scopes = [{}]
        self.structs = {}
        self.functions = {}
        self.current_fn = None
        self.current_struct = None
        self.current_this = None
        self.pending = []
        self.mut_final = False
        self.all_methods = []
        self.lambda_structs = []
        self.lambda_names = {}
        self.lambda_stack = []
        self.allow_lambda = False

    def context(self):
        return (self.scopes, self.current_fn, self.current_struct, self.current_this)

    def resolve_in(self, ctx, name, node):
        scopes, _, struct, this = ctx
        for frame in reversed(scopes):
            if name in frame:
                return frame[name], [], []
        if struct is not None and name in struct.index:
            idx = struct.index[name]
            tok = Token("identifier", name, node.line, node.col)
            return this, [idx], [(tok, struct.fields[idx])]
        return None

    def in_lambda(self):
        return bool(self.lambda_stack) and self.current_struct is self.lambda_stack[-1][2]

    def not_captured(self, node, name):
        if self.in_lambda():
            lname, outer, _ = self.lambda_stack[-1]
            if self.resolve_in(outer, name, node) is not None:
                raise CompileError(f"line {node.line}:{node.col}: '{name}' is not captured by lambda '{lname}': add it to the capture list, [{name}]")

    def lookup_root(self, node, name):
        found = self.resolve_in(self.context(), name, node)
        if found is not None:
            return found
        self.not_captured(node, name)
        s = self.current_struct
        if self.in_lambda():
            raise CompileError(f"line {node.line}:{node.col}: name '{name}' is not a parameter, a local variable or a capture of lambda '{self.lambda_stack[-1][0]}'")
        if s is not None:
            raise CompileError(f"line {node.line}:{node.col}: name '{name}' is not a parameter, a local variable or a field of '{s.name}'")
        raise CompileError(f"line {node.line}:{node.col}: variable '{name}' is used before its declaration")

    def is_lambda_type(self, type_name):
        return type_name in self.lambda_names

    def expr_label(self, expr):
        if isinstance(expr, VarNode):
            return expr.name
        if isinstance(expr, FieldNode):
            return ".".join(t.text for t in expr.names)
        return getattr(expr, "name", "value")

    def reject_lambda(self, expr, what):
        if not self.allow_lambda and self.is_lambda_type(getattr(expr, "type", None)):
            raise CompileError(f"line {expr.line}:{expr.col}: '{self.expr_label(expr)}' is a lambda and {what}")

    def resolve_path(self, node, names):
        decl, indices, links = self.lookup_root(node, names[0].text)
        curr_type = links[-1][1].type_name if links else decl.type_name
        indices = list(indices)
        links = list(links)
        for prev, tok in zip(names, names[1:]):
            curr_type = self.step_field(curr_type, prev.text, tok, indices, links)
        return decl, curr_type, indices, links

    def step_field(self, curr_type, prev_text, tok, indices, links):
        if self.is_lambda_type(curr_type):
            raise CompileError(f"line {tok.line}:{tok.col}: the captures of lambda '{self.lambda_names[curr_type]}' are not visible outside its body")
        if curr_type not in self.structs:
            raise CompileError(f"line {tok.line}:{tok.col}: cannot access field '{tok.text}': '{prev_text}' is not a struct, got {curr_type}")
        sdef = self.structs[curr_type]
        if tok.text not in sdef.index:
            raise CompileError(f"line {tok.line}:{tok.col}: struct '{curr_type}' has no field '{tok.text}'")
        idx = sdef.index[tok.text]
        field = sdef.fields[idx]
        indices.append(idx)
        links.append((tok, field))
        return field.type_name

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

    def visit_program(self, node):
        for s in node.structs:
            self.visit_struct_def(s)

        methods = [m for s in node.structs for m in s.methods]
        self.all_methods = list(methods)
        for m in methods:
            for p_type, _ in m.param_toks:
                self.check_type(p_type)
            self.check_type(m.ret_tok)

        for f in node.fns:
            if f.name in self.functions:
                raise CompileError(f"line {f.line}:{f.col}: function '{f.name}' is already declared")
            for p_type, _ in f.param_toks:
                self.check_type(p_type)
            self.check_type(f.ret_tok)
            self.functions[f.name] = f

        for s in node.structs:
            for m in s.methods:
                m.accept(self)

        changed = True
        while changed:
            changed = False
            for m in self.all_methods:
                if not m.mutating and any(c.mutating for c in m.calls_on_this):
                    m.mutating = True
                    changed = True

        for call, chain, bad in self.pending:
            self.check_mutating_call(call, chain, bad)
        self.mut_final = True

        for f in node.fns:
            f.accept(self)

        for s in node.stmts:
            s.accept(self)
        node.exit_node.accept(self)
        node.lambda_structs = self.lambda_structs

    def check_mutating_call(self, call, chain, bad):
        if call.fn.mutating and bad is not None and getattr(call, "label", None):
            raise CompileError(f"line {call.line}:{call.col}: cannot call '{call.label}': its 'call' changes it, and it is not mut")
        if call.fn.mutating and bad is not None:
            raise CompileError(f"line {call.line}:{call.col}: cannot call mutating '{call.name}' on '{chain}': '{bad}' is not mut")

    def register_call(self, call, obj):
        chain = None
        bad = None
        if obj is None:
            self.current_fn.calls_on_this.append(call.fn)
        elif is_addressable(obj):
            chain = obj.name if isinstance(obj, VarNode) else ".".join(t.text for t in obj.names)
            if not obj.decl.mutable:
                bad = obj.name if isinstance(obj, VarNode) else obj.names[0].text
            else:
                for tok, field in obj.links:
                    if not field.mutable:
                        bad = tok.text
                        break
            if obj.decl is self.current_this and self.current_this is not None:
                self.current_fn.calls_on_this.append(call.fn)
        if self.mut_final:
            self.check_mutating_call(call, chain, bad)
        else:
            self.pending.append((call, chain, bad))

    def check_args(self, node, fn, what, callee):
        if len(node.args) != len(fn.params):
            raise CompileError(f"line {node.line}:{node.col}: {what} needs {plural(len(fn.params), 'argument')}, got {len(node.args)}")
        for arg, (p_type, p_name) in zip(node.args, fn.params):
            arg.accept(self)
            self.reject_lambda(arg, f"cannot be passed to '{callee}': its type has no name, so no parameter can have it")
            self.check_assignable(arg, p_type, arg, f"initialise parameter '{p_name}'")

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

        for m in node.methods:
            if m.name in node.index:
                raise CompileError(f"line {m.name_tok.line}:{m.name_tok.col}: member function '{m.name}' has the same name as a field of struct '{node.name}'")
            if m.name in node.method_index:
                raise CompileError(f"line {m.name_tok.line}:{m.name_tok.col}: member function '{m.name}' is already declared in struct '{node.name}'")
            node.method_index[m.name] = m

        self.structs[node.name] = node

    def visit_fn_def(self, node):
        self.check_body(node, None)

    def visit_member_fn(self, node):
        self.check_body(node, self.structs[node.owner])

    def check_body(self, node, struct):
        frame = {}
        node.param_decls = []
        label = getattr(node, "label", node.name)
        for p_type, p_name in node.param_toks:
            if p_name.text in frame:
                raise CompileError(f"line {p_name.line}:{p_name.col}: parameter '{p_name.text}' is already declared in function '{label}'")
            decl = DeclNode(p_name.line, p_name.col, p_name.text, p_type, False, [], None)
            frame[p_name.text] = decl
            node.param_decls.append(decl)

        saved = self.context()
        self.scopes = [frame]
        self.current_fn = node
        self.current_struct = struct
        self.current_this = ThisDecl(struct) if struct else None
        node.this_decl = self.current_this
        for s in node.body.statements:
            s.accept(self)
        node.body.exit_node.accept(self)
        self.scopes, self.current_fn, self.current_struct, self.current_this = saved

    def visit_lambda(self, node):
        outer = self.context()
        seen = []
        fields = []
        inits = []
        for tok, mutable in node.captures:
            if tok.text in seen:
                raise CompileError(f"line {tok.line}:{tok.col}: '{tok.text}' is captured twice")
            seen.append(tok.text)
            found = self.resolve_in(outer, tok.text, tok)
            if found is None:
                raise CompileError(f"line {tok.line}:{tok.col}: cannot capture '{tok.text}': no variable '{tok.text}' is visible here")
            decl, _, links = found
            c_type = links[-1][1].type_name if links else decl.type_name
            fields.append(FieldDeclNode(tok.line, tok.col, Token("identifier", c_type, tok.line, tok.col), mutable, tok.text))
            inits.append(VarNode(tok.line, tok.col, tok.text))

        for p_type, p_name in node.param_toks:
            self.check_type(p_type)
            if p_name.text in seen:
                raise CompileError(f"line {p_name.line}:{p_name.col}: parameter '{p_name.text}' has the same name as a capture of lambda '{node.name}'")
        self.check_type(node.ret_tok)

        s_name = f"lambda.{node.name}"
        n = 1
        while s_name in self.structs:
            n += 1
            s_name = f"lambda.{node.name}.{n}"

        call_tok = Token("identifier", "call", node.name_tok.line, node.name_tok.col)
        method = MemberFnNode(node.line, node.col, call_tok, node.param_toks, node.ret_tok, node.body, s_name)
        method.label = node.name
        sdef = StructDefNode(node.line, node.col, s_name, fields, [method])
        for i, f in enumerate(fields):
            sdef.index[f.name] = i
        sdef.method_index["call"] = method
        self.structs[s_name] = sdef
        self.lambda_names[s_name] = node.name
        self.lambda_structs.append(sdef)
        self.all_methods.append(method)

        self.lambda_stack.append((node.name, outer, sdef))
        self.check_body(method, sdef)
        self.lambda_stack.pop()
        if self.mut_final and any(c.mutating for c in method.calls_on_this):
            method.mutating = True

        lbrace = Token("lbrace", "{", node.name_tok.line, node.name_tok.col)
        type_tok = Token("identifier", s_name, node.name_tok.line, node.name_tok.col)
        decl = DeclNode(node.name_tok.line, node.name_tok.col, node.name, type_tok, any(m for _, m in node.captures), inits, lbrace)
        self.allow_lambda = True
        self.visit_decl(decl)
        self.allow_lambda = False
        node.struct_def = sdef
        node.decl = decl

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
            self.reject_lambda(first, "cannot initialise a variable or a field: its type has no name")
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
                    self.reject_lambda(item, "cannot initialise a variable or a field: its type has no name")
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
            self.reject_lambda(node.inits[0], "cannot initialise a variable or a field: its type has no name")
            self.check_assignable(node.inits[0], node.type_name, node, f"initialise '{node.name}'")
        else:
            node.copy = self.check_init(node.inits, node.type_name, node.lbrace)

        top_frame[node.name] = node

    def visit_assign(self, node):
        root = node.names[0]
        decl, _, root_links = self.lookup_root(node, root.text)
        root_type = root_links[-1][1].type_name if root_links else decl.type_name
        if len(node.names) == 1 and self.is_lambda_type(root_type):
            raise CompileError(f"line {node.line}:{node.col}: cannot assign to '{node.name}': it is a lambda")

        if not decl.mutable:
            if len(node.names) == 1:
                raise CompileError(f"line {node.line}:{node.col}: cannot assign to '{node.name}': it is not mut")
            raise CompileError(f"line {root.line}:{root.col}: cannot assign to '{node.name}': '{root.text}' is not mut")
        decl, node.target_type, node.indices, links = self.resolve_path(node, node.names)
        for tok, field in links:
            if not field.mutable and decl is self.current_this and self.in_lambda():
                raise CompileError(f"line {node.line}:{node.col}: cannot assign to '{node.name}': the capture '{tok.text}' is const, write [mut {tok.text}]")
            if not field.mutable:
                raise CompileError(f"line {tok.line}:{tok.col}: cannot assign to '{node.name}': field '{tok.text}' is not mut")
        if decl is self.current_this and self.current_this is not None:
            self.current_fn.mutating = True

        if node.target_type in self.structs:
            bad = self.const_field(node.target_type)
            if bad:
                raise CompileError(f"line {node.line}:{node.col}: cannot assign to '{node.name}': field '{bad[1]}' of '{bad[0]}' is not mut")

        node.value.accept(self)
        self.reject_lambda(node.value, "cannot be assigned: its type has no name")
        self.check_assignable(node.value, node.target_type, node, f"assign to '{node.name}'")
        node.decl = decl

    def visit_exit(self, node):
        node.value.accept(self)
        self.reject_lambda(node.value, "cannot be the value of 'exit'")
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
            raise CompileError(f"line {node.value.line}:{node.value.col}: cannot exit from '{getattr(self.current_fn, "label", self.current_fn.name)}' of type {want} with a value of type {have}")
        node.ret_type = want

    def visit_call(self, node):
        s = self.current_struct
        own_method = s is not None and not self.in_lambda() and node.name in s.method_index
        is_function = own_method or node.name in self.functions
        if self.resolve_in(self.context(), node.name, node) is not None:
            if is_function:
                raise CompileError(f"line {node.line}:{node.col}: '{node.name}' is both a variable and a function: rename one of them")
            self.make_callable(node, VarNode(node.line, node.col, node.name), node.name)
            return

        if own_method:
            fn = s.method_index[node.name]
            self.check_args(node, fn, f"member function '{node.name}' of '{s.name}'", node.name)
            node.type = fn.ret_type
            node.fn = fn
            node.this_decl = self.current_this
            self.register_call(node, None)
            return

        if node.name not in self.functions:
            if any(name == node.name for name, _, _ in self.lambda_stack):
                raise CompileError(f"line {node.line}:{node.col}: lambda '{node.name}' cannot call itself")
            self.not_captured(node, node.name)
            raise CompileError(f"line {node.line}:{node.col}: function '{node.name}' is used before its declaration")

        fn = self.functions[node.name]
        self.check_args(node, fn, f"function '{node.name}'", node.name)
        node.type = fn.ret_type
        node.fn = fn

    def make_callable(self, node, obj, label):
        obj.accept(self)
        t = obj.type
        if t not in self.structs:
            raise CompileError(f"line {node.line}:{node.col}: '{label}' is not callable: it is {t}")
        sdef = self.structs[t]
        if "call" not in sdef.method_index:
            raise CompileError(f"line {node.line}:{node.col}: '{label}' is not callable: {t} has no member function 'call'")
        node.__class__ = CallableCallNode
        node.obj = obj
        node.name = "call"
        node.label = label
        fn = sdef.method_index["call"]
        self.check_args(node, fn, f"'{label}'", label)
        node.type = fn.ret_type
        node.fn = fn
        self.register_call(node, obj)

    def visit_member_call(self, node):
        obj = node.obj
        if isinstance(obj, VarNode) and obj.name in self.structs:
            found = any(obj.name in frame for frame in self.scopes) or (self.current_struct is not None and obj.name in self.current_struct.index)
            if not found:
                raise CompileError(f"line {obj.line}:{obj.col}: cannot call '{node.name}' on type '{obj.name}', a member function is called on an object")

        obj.accept(self)
        t = obj.type
        if t not in self.structs:
            raise CompileError(f"line {node.line}:{node.col}: cannot call '{node.name}' on a value of type {t}")
        sdef = self.structs[t]
        if node.name not in sdef.method_index and node.name in sdef.index and not self.is_lambda_type(t):
            tok = Token("identifier", node.name, node.line, node.col)
            if isinstance(obj, VarNode):
                field = FieldNode(obj.line, obj.col, [Token("identifier", obj.name, obj.line, obj.col), tok])
            elif isinstance(obj, FieldNode):
                field = FieldNode(obj.line, obj.col, obj.names + [tok])
            elif isinstance(obj, ResultFieldNode):
                field = ResultFieldNode(obj.line, obj.col, obj.obj, obj.names + [tok])
                field.dots = obj.dots + [tok]
            else:
                field = ResultFieldNode(node.line, node.col, obj, [tok])
                field.dots = [tok]
            self.make_callable(node, field, f"{self.expr_label(obj)}.{node.name}")
            return
        if node.name not in sdef.method_index:
            raise CompileError(f"line {node.line}:{node.col}: struct '{t}' has no member function '{node.name}'")

        fn = sdef.method_index[node.name]
        self.check_args(node, fn, f"member function '{node.name}' of '{t}'", node.name)
        node.type = fn.ret_type
        node.fn = fn
        self.register_call(node, obj)

    def visit_result_field(self, node):
        node.obj.accept(self)
        curr_type = node.obj.type
        node.indices = []
        links = []
        prev = node.obj.name if isinstance(node.obj, (CallNode, MemberCallNode)) else "read"
        for dot, tok in zip(node.dots, node.names):
            if curr_type not in self.structs:
                raise CompileError(f"line {dot.line}:{dot.col}: cannot access field '{tok.text}': the result of '{prev}' is not a struct, got {curr_type}")
            curr_type = self.step_field(curr_type, prev, tok, node.indices, links)
            prev = tok.text
        node.type = curr_type

    def visit_read(self, node):
        node.type = "i32"

    def visit_print(self, node):
        node.value.accept(self)
        self.reject_lambda(node.value, "cannot be printed")

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
        tok = Token("identifier", node.name, node.line, node.col)
        node.decl, node.type, node.indices, node.links = self.resolve_path(node, [tok])

    def visit_field(self, node):
        node.decl, node.type, node.indices, node.links = self.resolve_path(node, node.names)

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
    print_checked = False

    if "--ast" in args:
        print_ast = True
        args.remove("--ast")
    if "--ast-checked" in args:
        print_checked = True
        args.remove("--ast-checked")

    if print_ast or print_checked:
        if len(args) != 1:
            print(f"usage: {sys.argv[0]} [--ast | --ast-checked] input.txt", file=sys.stderr)
            sys.exit(1)
        input_path = args[0]
        output_path = None
    else:
        if len(args) != 2:
            print(f"usage: {sys.argv[0]} [--ast] input.txt output.ll", file=sys.stderr)
            sys.exit(1)
        input_path = args[0]
        output_path = args[1]

    module = ir.Module(name="practice8")
    module.triple = llvm.get_default_triple()

    main_func_type = ir.FunctionType(I32, [])
    main_function = ir.Function(module, main_func_type, name="main")
    builder = ir.IRBuilder(main_function.append_basic_block("entry"))

    printf_type = ir.FunctionType(I32, [ir.PointerType(I8)], var_arg=True)
    printf = ir.Function(module, printf_type, name="printf")
    scanf = ir.Function(module, printf_type, name="scanf")

    ctx = {
        "module": module,
        "printf": printf,
        "scanf": scanf,
        "fmt_int": build_global_str(module, "fmt_int", "Program exit with result %lld\n"),
        "fmt_str": build_global_str(module, "fmt_str", "Program exit with result %s\n"),
        "str_true": build_global_str(module, "str_true", "true"),
        "str_false": build_global_str(module, "str_false", "false")
    }
    ctx["strings"] = {"true": ctx["str_true"], "false": ctx["str_false"]}

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

        if print_checked:
            tree.dump()
            sys.exit(0)

        tree.codegen(builder, ctx)

        if output_path:
            with open(output_path, "w") as out:
                out.write(str(module))

    except CompileError as e:
        print(f"compilation error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
