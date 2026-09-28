; ModuleID = "practice4"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"a" = alloca i32
  store i32 10, i32* %"a"
  %"b" = alloca i64
  %"wide" = sext i32 10 to i64
  store i64 %"wide", i64* %"b"
  %"c" = alloca i1
  %"a_val" = load i32, i32* %"a"
  %"b_val" = load i64, i64* %"b"
  %"wide.1" = sext i32 %"a_val" to i64
  %".4" = icmp eq i64 %"wide.1", %"b_val"
  store i1 %".4", i1* %"c"
  %"c_val" = load i1, i1* %"c"
  %".6" = bitcast [5 x i8]* @"str_true" to i8*
  %".7" = bitcast [6 x i8]* @"str_false" to i8*
  %".8" = select  i1 %"c_val", i8* %".6", i8* %".7"
  %".9" = bitcast [29 x i8]* @"fmt_str" to i8*
  %".10" = call i32 (i8*, ...) @"printf"(i8* %".9", i8* %".8")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt_int" = private constant [31 x i8] c"Program exit with result %lld\0a\00"
@"fmt_str" = private constant [29 x i8] c"Program exit with result %s\0a\00"
@"str_true" = private constant [5 x i8] c"true\00"
@"str_false" = private constant [6 x i8] c"false\00"