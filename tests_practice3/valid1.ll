; ModuleID = "practice3"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"multmp" = mul i32 3, 4
  %"addtmp" = add i32 2, %"multmp"
  %"x" = alloca i32
  store i32 %"addtmp", i32* %"x"
  %"x_val" = load i32, i32* %"x"
  %".3" = bitcast [29 x i8]* @"fmt" to i8*
  %".4" = call i32 (i8*, ...) @"printf"(i8* %".3", i32 %"x_val")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt" = private constant [29 x i8] c"Program exit with result %d\0a\00"