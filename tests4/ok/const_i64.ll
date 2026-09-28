; ModuleID = "practice4"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"x" = alloca i64
  store i64 4294967296, i64* %"x"
  %"x_val" = load i64, i64* %"x"
  %".3" = bitcast [31 x i8]* @"fmt_int" to i8*
  %".4" = call i32 (i8*, ...) @"printf"(i8* %".3", i64 %"x_val")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt_int" = private constant [31 x i8] c"Program exit with result %lld\0a\00"
@"fmt_str" = private constant [29 x i8] c"Program exit with result %s\0a\00"
@"str_true" = private constant [5 x i8] c"true\00"
@"str_false" = private constant [6 x i8] c"false\00"