; ModuleID = "practice2"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %".2" = bitcast [29 x i8]* @"fmt" to i8*
  %".3" = call i32 (i8*, ...) @"printf"(i8* %".2", i32 42)
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt" = private constant [29 x i8] c"Program exit with result %d\0a\00"