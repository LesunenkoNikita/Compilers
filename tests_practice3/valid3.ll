; ModuleID = "practice3"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"subtmp" = sub i32 10, 3
  %"subtmp.1" = sub i32 %"subtmp", 2
  %"a" = alloca i32
  store i32 %"subtmp.1", i32* %"a"
  %"a_val" = load i32, i32* %"a"
  %".3" = bitcast [29 x i8]* @"fmt" to i8*
  %".4" = call i32 (i8*, ...) @"printf"(i8* %".3", i32 %"a_val")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt" = private constant [29 x i8] c"Program exit with result %d\0a\00"