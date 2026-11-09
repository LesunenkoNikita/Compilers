import sys
import os
import subprocess
import glob
import difflib


def check_snapshot(test_file, ext, flags, update):
    snap_file = test_file[:-len(".txt")] + ext

    comp = subprocess.run(
        [sys.executable, "compiler.py", *flags, test_file],
        capture_output=True,
        text=True
    )

    if comp.returncode != 0:
        return False, f"{ext} generation failed", comp.stderr

    new_lines = comp.stdout.splitlines(keepends=True)
    if not os.path.exists(snap_file):
        with open(snap_file, "w") as f:
            f.writelines(new_lines)
        return True, f"{ext} created", ""

    with open(snap_file, "r") as f:
        old_lines = f.readlines()
    if old_lines == new_lines:
        return True, f"{ext} matched", ""

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

    if not update:
        return False, f"{ext} differs from the compiler output, rerun with --update-ast to accept the changed lines", "".join(report)

    with open(snap_file, "w") as f:
        f.writelines(patched)
    return True, f"{ext} updated, changed lines", "".join(report)


def run_program(test_file, ll_file, optimize):
    flags = ["--remove-unused"] if optimize else []
    comp = subprocess.run(
        [sys.executable, "compiler.py", *flags, test_file, ll_file],
        capture_output=True,
        text=True
    )

    if comp.returncode != 0:
        return False, comp.stderr

    input_file = test_file[:-len(".txt")] + ".in"
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
    return True, exec_run.stdout + exec_run.stderr


def is_opt_test(test_file):
    return os.path.basename(os.path.dirname(test_file)) == "opt"


def expected_outcome(test_file):
    folder = os.path.basename(os.path.dirname(test_file))
    name = os.path.basename(test_file)
    if folder in ("ok", "opt") or name.startswith("valid"):
        return "compile"
    if folder == "err" or name.startswith("invalid"):
        return "error"
    return None


def main():
    args = sys.argv[1:]
    update = "--update-ast" in args
    if "--both" in args:
        modes = [False, True]
    elif "--remove-unused" in args or os.environ.get("REMOVE_UNUSED") == "1":
        modes = [True]
    else:
        modes = [False]

    all_txt_files = glob.glob("**/*.txt", recursive=True)

    test_files = sorted(
        f for f in all_txt_files
        if os.path.basename(f) != "ai_usage.txt"
        and not f.startswith("lcd/")
        and not f.startswith("venv/")
        and not f.startswith(".venv/")
    )

    passed = 0
    failed = 0

    if not test_files:
        print("No .txt test files found.")
        sys.exit(0)

    ll_dir = "ll_out"
    os.makedirs(ll_dir, exist_ok=True)

    for test_file in test_files:
        expected_file = test_file[:-len(".txt")] + ".expected"
        if not os.path.exists(expected_file):
            print(f"[{test_file}] SKIPPED: missing {expected_file}")
            continue

        with open(expected_file, "r") as f:
            expected = f.read()

        ll_file = os.path.join(ll_dir, os.path.basename(test_file).replace(".txt", ".ll"))
        opt_test = is_opt_test(test_file)
        test_modes = [False, True] if opt_test else modes

        for optimize in test_modes:
            label = f"[{test_file}]" + (" [--remove-unused]" if optimize else "")
            compiled, actual = run_program(test_file, ll_file, optimize)

            outcome = expected_outcome(test_file)
            if outcome == "compile" and not compiled:
                print(f"{label} FAILED (a program in this folder must compile)")
                print(actual, end="")
                failed += 1
                continue
            if outcome == "error" and compiled:
                print(f"{label} FAILED (a program in this folder must be rejected with a compilation error)")
                print(actual, end="")
                failed += 1
                continue

            if actual != expected:
                print(f"{label} FAILED")
                print("--- EXPECTED ---")
                print(expected, end="")
                print("--- ACTUAL ---")
                print(actual, end="")
                failed += 1
                continue

            if not compiled:
                print(f"{label} PASSED")
                passed += 1
                continue

            if opt_test:
                snap_ok, snap_msg, detail = check_snapshot(test_file, ".astc", ["--remove-unused", "--ast-checked"], update)
            else:
                snap_ok, snap_msg, detail = check_snapshot(test_file, ".ast", ["--ast"], update)
            if snap_ok:
                msg = label + " PASSED"
                if not snap_msg.endswith("matched"):
                    msg += f" ({snap_msg})"
                print(msg)
                print(detail, end="")
                passed += 1
            else:
                print(f"{label} FAILED ({snap_msg})")
                print(detail, end="")
                failed += 1

    print(f"\nTotal: {passed + failed}, Passed: {passed}, Failed: {failed}")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

