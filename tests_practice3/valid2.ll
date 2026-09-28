; ModuleID = "practice4"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"x" = alloca i32
  %"multmp" = mul i32 2, 3
  %"addtmp" = add i32 1, %"multmp"
  %"addtmp.1" = add i32 %"addtmp", 4
  store i32 %"addtmp.1", i32* %"x"
  %"x_val" = load i32, i32* %"x"
  %"wide" = sext i32 %"x_val" to i64
  %".3" = bitcast [31 x i8]* @"fmt_int" to i8*
  %".4" = call i32 (i8*, ...) @"printf"(i8* %".3", i64 %"wide")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt_int" = private constant [31 x i8] c"Program exit with result %lld\0a\00"
@"fmt_str" = private constant [29 x i8] c"Program exit with result %s\0a\00"
@"str_true" = private constant [5 x i8] c"true\00"
@"str_false" = private constant [6 x i8] c"false\00"