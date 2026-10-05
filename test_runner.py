import sys
import os
import subprocess
import glob


def update_ast(test_file):
    ast_file = test_file.replace(".txt", ".ast")
    
    ast_comp = subprocess.run(
        [sys.executable, "compiler.py", "--ast", test_file],
        capture_output=True,
        text=True
    )
    
    if ast_comp.returncode == 0:
        new_ast = ast_comp.stdout
        if os.path.exists(ast_file):
            with open(ast_file, "r") as f:
                old_ast = f.read()
            if old_ast != new_ast:
                with open(ast_file, "w") as f:
                    f.write(new_ast)
                return "AST updated"
            else:
                return ""
        else:
            with open(ast_file, "w") as f:
                f.write(new_ast)
            return "AST created"
    return "AST generation failed"


def main():
    all_txt_files = glob.glob("**/*.txt", recursive=True)
    
    test_files = [
        f for f in all_txt_files 
        if os.path.basename(f) != "ai_usage.txt"
        and not f.startswith("lcd/")
        and not f.startswith("venv/")
        and not f.startswith(".venv/")
    ]

    passed = 0
    failed = 0

    if not test_files:
        print("No .txt test files found.")
        sys.exit(0)

    ll_dir = "ll_out"
    os.makedirs(ll_dir, exist_ok=True)

    for test_file in test_files:
        expected_file = test_file.replace(".txt", ".expected")
        if not os.path.exists(expected_file):
            print(f"[{test_file}] SKIPPED: missing {expected_file}")
            continue

        with open(expected_file, "r") as f:
            expected = f.read()

        ll_file = os.path.join(ll_dir, os.path.basename(test_file).replace(".txt", ".ll"))

        comp = subprocess.run(
            [sys.executable, "compiler.py", test_file, ll_file],
            capture_output=True,
            text=True
        )

        ast_msg = ""
        if comp.returncode != 0:
            actual = comp.stderr
        else:
            exec_run = subprocess.run(
                ["lli", ll_file],
                capture_output=True,
                text=True
            )
            actual = exec_run.stdout + exec_run.stderr
            
            ast_msg = update_ast(test_file)

        if actual == expected:
            msg = f"[{test_file}] PASSED"
            if ast_msg:
                msg += f" ({ast_msg})"
            print(msg)
            passed += 1
        else:
            print(f"[{test_file}] FAILED")
            print("--- EXPECTED ---")
            print(expected, end="")
            print("--- ACTUAL ---")
            print(actual, end="")
            failed += 1

    print(f"\nTotal: {passed + failed}, Passed: {passed}, Failed: {failed}")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
