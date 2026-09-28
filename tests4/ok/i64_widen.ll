; ModuleID = "practice4"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"a" = alloca i32
  store i32 10, i32* %"a"
  %"b" = alloca i64
  %"a_val" = load i32, i32* %"a"
  %"wide" = sext i32 %"a_val" to i64
  store i64 %"wide", i64* %"b"
  %"a_val.1" = load i32, i32* %"a"
  %"b_val" = load i64, i64* %"b"
  %"wide.1" = sext i32 %"a_val.1" to i64
  %"addtmp" = add i64 %"wide.1", %"b_val"
  store i64 %"addtmp", i64* %"b"
  %"b_val.1" = load i64, i64* %"b"
  %".5" = bitcast [31 x i8]* @"fmt_int" to i8*
  %".6" = call i32 (i8*, ...) @"printf"(i8* %".5", i64 %"b_val.1")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt_int" = private constant [31 x i8] c"Program exit with result %lld\0a\00"
@"fmt_str" = private constant [29 x i8] c"Program exit with result %s\0a\00"
@"str_true" = private constant [5 x i8] c"true\00"
@"str_false" = private constant [6 x i8] c"false\00"