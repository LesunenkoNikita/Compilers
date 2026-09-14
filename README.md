***After pulling a repo, here is a list of commands to test the compiler:***  
source ~/lcd/bin/activate  
python3 compiler.py tests/valid_test1.txt output.ll  
lli output.ll  
***or, additionally:***  
llc -filetype=obj -relocation-model=pic output.ll -o output.o  
clang -fPIE output.o -o program && ./program  
