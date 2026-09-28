; ModuleID = "practice4"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"x" = alloca i32
  store i32 10, i32* %"x"
  %"y" = alloca i32
  %"x_val" = load i32, i32* %"x"
  %"addtmp" = add i32 %"x_val", 5
  store i32 %"addtmp", i32* %"y"
  %"y_val" = load i32, i32* %"y"
  %"multmp" = mul i32 %"y_val", 2
  store i32 %"multmp", i32* %"y"
  %"y_val.1" = load i32, i32* %"y"
  %"wide" = sext i32 %"y_val.1" to i64
  %".5" = bitcast [31 x i8]* @"fmt_int" to i8*
  %".6" = call i32 (i8*, ...) @"printf"(i8* %".5", i64 %"wide")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt_int" = private constant [31 x i8] c"Program exit with result %lld\0a\00"
@"fmt_str" = private constant [29 x i8] c"Program exit with result %s\0a\00"
@"str_true" = private constant [5 x i8] c"true\00"
@"str_false" = private constant [6 x i8] c"false\00"