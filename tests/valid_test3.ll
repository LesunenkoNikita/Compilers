; ModuleID = "practice2"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"x" = alloca i32
  store i32 5, i32* %"x"
  %"y" = alloca i32
  store i32 10, i32* %"y"
  %"x_value" = load i32, i32* %"x"
  %"y_value" = load i32, i32* %"y"
  %"addtmp" = add i32 %"x_value", %"y_value"
  %"z" = alloca i32
  store i32 %"addtmp", i32* %"z"
  %"z_value" = load i32, i32* %"z"
  %"multmp" = mul i32 %"z_value", 2
  store i32 %"multmp", i32* %"y"
  %"y_exit" = load i32, i32* %"y"
  %".6" = bitcast [29 x i8]* @"fmt" to i8*
  %".7" = call i32 (i8*, ...) @"printf"(i8* %".6", i32 %"y_exit")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt" = private constant [29 x i8] c"Program exit with result %d\0a\00"