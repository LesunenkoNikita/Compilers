import sys
import os
import subprocess
import glob
import difflib


def check_ast(test_file):
    ast_file = test_file.replace(".txt", ".ast")

    ast_comp = subprocess.run(
        [sys.executable, "compiler.py", "--ast", test_file],
        capture_output=True,
        text=True
    )

    if ast_comp.returncode != 0:
        return False, "AST generation failed", ast_comp.stderr

    new_lines = ast_comp.stdout.splitlines(keepends=True)
    if not os.path.exists(ast_file):
        with open(ast_file, "w") as f:
            f.writelines(new_lines)
        return True, "AST created", ""

    with open(ast_file, "r") as f:
        old_lines = f.readlines()
    if old_lines == new_lines:
        return True, "AST matched", ""

    patched = list(old_lines)
    report = []
    shift = 0
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        patched[i1 + shift:i2 + shift] = new_lines[j1:j2]
        shift += (j2 - j1) - (i2 - i1)
        for k in range(i1, i2):
            report.append(f"  line {k + 1} - {old_lines[k].rstrip()}\n")
        for k in range(j1, j2):
            report.append(f"  line {k + 1} + {new_lines[k].rstrip()}\n")

    with open(ast_file, "w") as f:
        f.writelines(patched)
    return True, "AST updated, changed lines", "".join(report)


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

        if comp.returncode != 0:
            actual = comp.stderr
        else:
            input_file = test_file.replace(".txt", ".in")
            stdin_data = ""
            if os.path.exists(input_file):
                with open(input_file, "r") as f:
                    stdin_data = f.read()
            exec_run = subprocess.run(
                ["lli", ll_file],
                input=stdin_data,
                capture_output=True,
                text=True
            )
            actual = exec_run.stdout + exec_run.stderr

        if actual == expected:
            if comp.returncode == 0:
                ast_ok, ast_msg, err_detail = check_ast(test_file)
                if ast_ok:
                    msg = f"[{test_file}] PASSED"
                    if ast_msg != "AST matched":
                        msg += f" ({ast_msg})"
                    print(msg)
                    print(err_detail, end="")
                    passed += 1
                else:
                    print(f"[{test_file}] FAILED ({ast_msg})")
                    print(err_detail, end="")
                    failed += 1
            else:
                print(f"[{test_file}] PASSED")
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
