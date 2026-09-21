; ModuleID = "practice2"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"x" = alloca i32
  store i32 10, i32* %"x"
  %"x_value" = load i32, i32* %"x"
  %"addtmp" = add i32 %"x_value", 5
  %"y" = alloca i32
  store i32 %"addtmp", i32* %"y"
  %"y_value" = load i32, i32* %"y"
  %"multmp" = mul i32 %"y_value", 2
  store i32 %"multmp", i32* %"y"
  %"y_exit" = load i32, i32* %"y"
  %".5" = bitcast [29 x i8]* @"fmt" to i8*
  %".6" = call i32 (i8*, ...) @"printf"(i8* %".5", i32 %"y_exit")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt" = private constant [29 x i8] c"Program exit with result %d\0a\00"