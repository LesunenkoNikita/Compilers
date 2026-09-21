import sys
import os
import subprocess
import glob


def main():
    all_txt_files = glob.glob("**/*.txt", recursive=True)
    
    # Filter out ai_usage.txt and virtual environment folders
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

    for test_file in test_files:
        expected_file = test_file.replace(".txt", ".expected")
        if not os.path.exists(expected_file):
            print(f"[{test_file}] SKIPPED: missing {expected_file}")
            continue

        with open(expected_file, "r") as f:
            expected = f.read()

        ll_file = test_file.replace(".txt", ".ll")

        comp = subprocess.run(
            [sys.executable, "compiler.py", test_file, ll_file],
            capture_output=True,
            text=True
        )

        if comp.returncode != 0:
            actual = comp.stderr
        else:
            exec_run = subprocess.run(
                ["lli", ll_file],
                capture_output=True,
                text=True
            )
            actual = exec_run.stdout + exec_run.stderr

        if actual == expected:
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
