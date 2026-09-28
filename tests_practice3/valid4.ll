; ModuleID = "practice3"
target triple = "aarch64-unknown-linux-gnu"
target datalayout = ""

define i32 @"main"()
{
entry:
  %"a" = alloca i32
  store i32 10, i32* %"a"
  %"a_val" = load i32, i32* %"a"
  %"multmp" = mul i32 %"a_val", 2
  %"subtmp" = sub i32 %"multmp", 1
  store i32 %"subtmp", i32* %"a"
  %"a_val.1" = load i32, i32* %"a"
  %".4" = bitcast [29 x i8]* @"fmt" to i8*
  %".5" = call i32 (i8*, ...) @"printf"(i8* %".4", i32 %"a_val.1")
  ret i32 0
}

declare i32 @"printf"(i8* %".1", ...)

@"fmt" = private constant [29 x i8] c"Program exit with result %d\0a\00"