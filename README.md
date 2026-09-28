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
