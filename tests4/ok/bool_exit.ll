; ModuleID = "practice4"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"x" = alloca i1
  store i1 1, i1* %"x"
  %"x_val" = load i1, i1* %"x"
  %".3" = bitcast [5 x i8]* @"str_true" to i8*
  %".4" = bitcast [6 x i8]* @"str_false" to i8*
  %".5" = select  i1 %"x_val", i8* %".3", i8* %".4"
  %".6" = bitcast [29 x i8]* @"fmt_str" to i8*
  %".7" = call i32 (i8*, ...) @"printf"(i8* %".6", i8* %".5")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt_int" = private constant [31 x i8] c"Program exit with result %lld\0a\00"
@"fmt_str" = private constant [29 x i8] c"Program exit with result %s\0a\00"
@"str_true" = private constant [5 x i8] c"true\00"
@"str_false" = private constant [6 x i8] c"false\00"