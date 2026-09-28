; ModuleID = "practice4"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"a" = alloca i32
  %"subtmp" = sub i32 10, 3
  %"subtmp.1" = sub i32 %"subtmp", 2
  store i32 %"subtmp.1", i32* %"a"
  %"a_val" = load i32, i32* %"a"
  %"wide" = sext i32 %"a_val" to i64
  %".3" = bitcast [31 x i8]* @"fmt_int" to i8*
  %".4" = call i32 (i8*, ...) @"printf"(i8* %".3", i64 %"wide")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt_int" = private constant [31 x i8] c"Program exit with result %lld\0a\00"
@"fmt_str" = private constant [29 x i8] c"Program exit with result %s\0a\00"
@"str_true" = private constant [5 x i8] c"true\00"
@"str_false" = private constant [6 x i8] c"false\00"