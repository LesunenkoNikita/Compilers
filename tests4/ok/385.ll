; ModuleID = "practice4"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"a" = alloca i64
  %"wide" = sext i32 10 to i64
  store i64 %"wide", i64* %"a"
  %"b" = alloca i1
  store i1 1, i1* %"b"
  %"c" = alloca i1
  store i1 0, i1* %"c"
  %"d" = alloca i1
  %"a_val" = load i64, i64* %"a"
  %"wide.1" = sext i32 10 to i64
  %".5" = icmp eq i64 %"a_val", %"wide.1"
  store i1 %".5", i1* %"d"
  %"e" = alloca i1
  %"a_val.1" = load i64, i64* %"a"
  %"wide.2" = sext i32 10 to i64
  %".7" = icmp ne i64 %"a_val.1", %"wide.2"
  store i1 %".7", i1* %"e"
  %"b_val" = load i1, i1* %"b"
  %"d_val" = load i1, i1* %"d"
  %".9" = icmp eq i1 %"b_val", %"d_val"
  store i1 %".9", i1* %"e"
  %"x" = alloca i32
  store i32 15, i32* %"x"
  %"y" = alloca i64
  %"x_val" = load i32, i32* %"x"
  %"wide.3" = sext i32 %"x_val" to i64
  store i64 %"wide.3", i64* %"y"
  %"z" = alloca i64
  %"x_val.1" = load i32, i32* %"x"
  %"addtmp" = add i32 %"x_val.1", 10
  %"wide.4" = sext i32 %"addtmp" to i64
  store i64 %"wide.4", i64* %"z"
  %"y_val" = load i64, i64* %"y"
  %"z_val" = load i64, i64* %"z"
  %"multmp" = mul i64 %"y_val", %"z_val"
  %"a_val.2" = load i64, i64* %"a"
  %"addtmp.1" = add i64 %"multmp", %"a_val.2"
  store i64 %"addtmp.1", i64* %"y"
  %"y_val.1" = load i64, i64* %"y"
  %".15" = bitcast [31 x i8]* @"fmt_int" to i8*
  %".16" = call i32 (i8*, ...) @"printf"(i8* %".15", i64 %"y_val.1")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt_int" = private constant [31 x i8] c"Program exit with result %lld\0a\00"
@"fmt_str" = private constant [29 x i8] c"Program exit with result %s\0a\00"
@"str_true" = private constant [5 x i8] c"true\00"
@"str_false" = private constant [6 x i8] c"false\00"