To launch a compiler execute these commands:  
source ~/lcd/bin/activate  
python3 test_runner.py  
  
for a specific file:  
python3 compiler.py <input.txt> output.ll  
lli output.ll  

optional:  
llc -filetype=obj -relocation-model=pic output.ll -o output.o  
clang -fPIE output.o -o program && ./program  
  
optional(for seeing AST for week 3 Task 2):  
python3 compiler.py --ast <input.txt>  
  
optional(for seeing tokens option):  
python3 compiler.py --tokens <input.txt>  
  
optional(for seeing the tree after the semantic pass, week 8):  
python3 compiler.py --ast-checked <input.txt>  
  
## Optimizations  
  
`--remove-unused` (week 9) runs an optimization pass on the checked tree, after the semantic pass and before code generation. The flag may stand anywhere on the command line:  
python3 compiler.py --remove-unused input.txt output.ll  
python3 compiler.py --remove-unused --ast-checked input.txt  
  
The pass removes declarations nobody reads (with the assignments to them), and global functions nobody calls, and repeats until a round removes nothing. A value that calls a function with an effect (print, read(), a mutating member function, a while loop, recursion, or a call of such a function) is always kept. Without the flag the compiler behaves exactly as before.  
  
Tests:  
python3 test_runner.py                     # every test without the flag  
python3 test_runner.py --remove-unused     # every test with the flag (same as REMOVE_UNUSED=1 python3 test_runner.py)  
python3 test_runner.py --both              # every test twice: without and with the flag  
Programs in tests9/opt always run both ways: NAME.expected must match with and without the flag, and NAME.astc is the tree printed by --remove-unused --ast-checked.  
A program in an ok or opt folder (or named valid...) must compile, and a program in an err folder (or named invalid...) must be rejected with a compilation error; otherwise the test fails even if its .expected matches.  
A missing .ast / .astc snapshot is created automatically. If an existing snapshot differs from the compiler output, the test fails and the runner prints the changed lines without touching the file; after reading them, accept the change with:  
python3 test_runner.py --update-ast  
  
Limits of counting:  
- A variable that only feeds itself, k := k + 1 with nobody else reading k, survives: the right side counts as a read.  
- Two functions that call only each other (or one that calls itself) never reach zero calls, so they stay. Counting cannot see a cycle, for the same reason reference counting cannot free one.  
  
Who frees a removed subtree:  
- The compiler is written in Python (CPython 3.14). CPython frees an object as soon as its reference count drops to zero; a separate cycle collector (gc) frees groups of objects that only point at each other.  
- The tree nodes keep no pointer back to their parent: a node points only to its children, and a name points sideways to its declaration (VarNode.decl, CallNode.fn). When the pass rebuilds a block's statement list without a dead declaration, that list was the only owner of the node, so its count drops to zero and it is freed at once, together with its subtree. If nodes kept a parent pointer, a child and its parent would point at each other, the count would never reach zero, and only the cycle collector could free the removed subtree.  
- Measurement (weakref.ref to a removed node, with gc.disable() and without gc.collect()): a dead declaration inside an if block is alive before the pass (one reference: its block's list) and the weakref returns None right after the pass. A removed top-level declaration and a removed function stay alive until the semantic checker is dropped, because its symbol tables (the top-level scope and the function table) still point at them; after that the weakref returns None, also without gc.collect().  
- This is the compiler's memory, not the compiled program's: the language has no heap yet, so nothing is freed in the binary.  
