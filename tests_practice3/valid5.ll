; ModuleID = "practice3"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"x" = alloca i32
  store i32 0, i32* %"x"
  %"y" = alloca i32
  store i32 10, i32* %"y"
  %"addtmp" = add i32 2, 5
  %"z" = alloca i32
  store i32 %"addtmp", i32* %"z"
  %"x_val" = load i32, i32* %"x"
  %"addtmp.1" = add i32 %"x_val", 10
  %"t" = alloca i32
  store i32 %"addtmp.1", i32* %"t"
  %"t_val" = load i32, i32* %"t"
  %"z_val" = load i32, i32* %"z"
  %"multmp" = mul i32 %"t_val", %"z_val"
  store i32 %"multmp", i32* %"t"
  %"t_val.1" = load i32, i32* %"t"
  %".7" = bitcast [29 x i8]* @"fmt" to i8*
  %".8" = call i32 (i8*, ...) @"printf"(i8* %".7", i32 %"t_val.1")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt" = private constant [29 x i8] c"Program exit with result %d\0a\00"