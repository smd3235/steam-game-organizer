"""Module-split audit and heal tool.

Scans project Python files for oversized modules that are candidates for splitting
into smaller modules, and can heal them by extracting a class or function into its
own module file.

Run directly:  python tools\audit_module_splits.py

Audit mode (default):
  Lists every .py file over the size threshold, with its top-level classes and
  functions, line counts, and suggested extract targets.

Heal mode (--heal FILE SYMBOL):
  Extracts SYMBOL (a top-level class or function) from FILE into a new module under
  core/ or services/ based on FILE's directory, rewrites FILE to import SYMBOL from
  the new module, and adds a change comment to both files.

Exits 0 on success; exits 1 on error or when audit finds oversized files.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Directories that are never scanned or written: frozen outputs, bundled runtime, git.
SKIP_DIRS = {".git", "dist", "build", "runtime", "__pycache__", ".pytest_cache", ".agent-cache", ".ruff_cache"}

# Files over this many lines are flagged as oversized split candidates.
OVER_SIZE_LINES = 300
# Files over this many bytes are also flagged (catches files with long lines).
OVER_SIZE_BYTES = 15000

# Project root is the parent of the tools/ directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

def iter_source_files(root: Path):
    """Yield every .py file under root, skipping vendored/output directories."""
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path

def parse_source(path: Path):
    """Return the AST module for path, or None if it cannot be parsed."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return ast.parse(text, filename=str(path))
    except SyntaxError:
        return None

def symbol_line_count(node: ast.AST) -> int:
    """Number of source lines occupied by a node (inclusive of decorators)."""
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None)
    if start is None or end is None:
        return 0
    return end - start + 1

def audit_file(path: Path, threshold_lines: int = OVER_SIZE_LINES, threshold_bytes: int = OVER_SIZE_BYTES):
    """Return a dict describing oversized split candidates in one file."""
    tree = parse_source(path)
    if tree is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    total_lines = text.count("\n") + 1
    total_bytes = len(text.encode("utf-8"))
    oversized = total_lines > threshold_lines or total_bytes > threshold_bytes
    classes = []
    functions = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            classes.append(
                {
                    "name": node.name,
                    "lines": symbol_line_count(node),
                    "methods": len(methods),
                    "decorators": len(node.decorator_list),
                    "line": node.lineno,
                }
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "lines": symbol_line_count(node),
                    "decorators": len(node.decorator_list),
                    "line": node.lineno,
                }
            )
    return {
        "path": path,
        "total_lines": total_lines,
        "total_bytes": total_bytes,
        "oversized": oversized,
        "classes": classes,
        "functions": functions,
    }

def suggest_module_name(file_path: Path, symbol_name: str) -> str:
    """Suggest a module file name for an extracted symbol.

    Files under services/ -> core/ or services/; files under ui/ -> ui/; etc.
    The module name is derived from the symbol name (snake_case).
    """
    rel = file_path.relative_to(PROJECT_ROOT)
    parts = list(rel.parts[:-1])  # drop the file name
    target_dir = parts[0] if parts else "core"
    snake = "".join("_" + c.lower() if c.isupper() else c for c in symbol_name).lstrip("_")
    return f"{target_dir}/{snake}.py"

def extract_symbol_names(code_text: str) -> set[str]:
    """Return the set of top-level names defined by code_text (classes/functions)."""
    names = set()
    try:
        tree = ast.parse(code_text)
    except SyntaxError:
        return names
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names

def needed_imports_for_symbol(source_text: str, symbol_name: str, source_module: str | None = None) -> list[str]:
    """Guess which module-level imports the extracted symbol needs.

    Scans the full source for import statements and returns those whose names are
    referenced inside the extracted symbol's body. Also finds module-level
    definitions (classes, functions, variables) referenced by the symbol that
    are defined in the source file itself, and adds imports for them from the
    source module. This is a heuristic: it may over- or under-import, so the
    caller should review.
    """
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return []
    # Find the symbol node.
    symbol_node = None
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol_name:
            symbol_node = node
            break
    if symbol_node is None:
        return []
    # Collect every Name node inside the symbol body.
    referenced: set[str] = set()
    for child in ast.walk(symbol_node):
        if isinstance(child, ast.Name):
            referenced.add(child.id)
    # Also attribute roots like os.path -> os.
    for child in ast.walk(symbol_node):
        if isinstance(child, ast.Attribute):
            referenced.add(child.attr)
    imports: list[str] = []
    imported_names: set[str] = set()
    module_level_names: dict[str, str] = {}  # name -> kind (class/function/var)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imported_names.add(name)
                if name in referenced:
                    imports.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            for alias in node.names:
                name = alias.asname or alias.name
                imported_names.add(name)
                if name in referenced:
                    imports.append(f"from {node.module} import {alias.name}")
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            module_level_names[node.name] = node.__class__.__name__
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_level_names[target.id] = "var"
    # Add imports for module-level definitions referenced by the symbol
    # but defined in the source file itself (not imported).
    if source_module:
        for name in referenced:
            if name not in imported_names and name in module_level_names:
                imports.append(f"from {source_module} import {name}")
    return imports



def heal_file(file_path: Path, symbol_name: str):
    """Extract symbol_name from file_path into a new module and update imports.

    Returns the new module path on success.
    """
    text = file_path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(file_path))
    # Find the symbol node and its surrounding lines.
    symbol_node = None
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol_name:
            symbol_node = node
            break
    if symbol_node is None:
        print(f"Error: {symbol_name!r} not found as a top-level class or function in {file_path}")
        sys.exit(1)
    start = symbol_node.lineno - 1
    end = symbol_node.end_lineno  # 1-indexed inclusive
    # Capture any leading decorators separately (they are part of the node already).
    symbol_lines = text.splitlines(keepends=True)[start:end]
    # Determine imports the symbol needs.
    source_module = file_path.relative_to(PROJECT_ROOT).as_posix().replace("/", ".")[:-3]
    imports = needed_imports_for_symbol(text, symbol_name, source_module)
    # Build the new module content.
    new_module = PROJECT_ROOT / suggest_module_name(file_path, symbol_name)
    new_module.parent.mkdir(parents=True, exist_ok=True)
    module_lines = [
        '"""Extracted from ' + str(file_path.relative_to(PROJECT_ROOT)).replace('//', '/') + '.\n',
        "\n",
        f"    {symbol_name} was moved here during a module split so the original file\n",
        "    stays under the size threshold. Import it from here instead of defining it\n",
        "    inline.\n",
        '"""\n',
        "\n",
    ]
    for imp in imports:
        module_lines.append(imp + "\n")
    if imports:
        module_lines.append("\n")
    module_lines.append("\n")
    module_lines.extend(symbol_lines)
    # Ensure trailing newline.
    if module_lines and not module_lines[-1].endswith("\n"):
        module_lines[-1] += "\n"
    new_module.write_text("".join(module_lines), encoding="utf-8")
    # Add change comment to the new module.
    print(f"Created {new_module.relative_to(PROJECT_ROOT)} with {symbol_name} ({symbol_node.lineno}-{end}).")
    # Now rewrite the original file: replace the symbol definition with an import.
    lines = text.splitlines(keepends=True)
    # Find where to insert the import: after the last import in the file, or at top.
    insert_at = 0
    last_import_idx = -1
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import_idx = max(last_import_idx, node.lineno - 1)
    if last_import_idx >= 0:
        insert_at = last_import_idx + 1
    # Remove trailing blank lines after imports to place import cleanly.
    while insert_at < len(lines) and lines[insert_at].strip() == "":
        insert_at += 1
    import_stmt = f"from {new_module.relative_to(PROJECT_ROOT).as_posix()[:-3].replace('/', '.')} import {symbol_name}\n"
    # Remove the symbol definition from the original.
    del lines[start:end]
    # Insert the import statement.
    lines.insert(insert_at, import_stmt)
    # Add a comment above the import explaining the change.
    comment = f"# {symbol_name} extracted to {new_module.relative_to(PROJECT_ROOT)} — see that module for its definition.\n"
    lines.insert(insert_at, comment)
    # Fix double blank lines.
    result = "".join(lines)
    result = result.replace("\n\n\n", "\n\n")
    file_path.write_text(result, encoding="utf-8")
    print(f"Updated {file_path.relative_to(PROJECT_ROOT)}: replaced {symbol_name} with import from new module.")
    return new_module


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and heal oversized Python modules by splitting them.")
    parser.add_argument("--heal", metavar="FILE:SYMBOL", help="Extract SYMBOL from FILE into a new module.")
    parser.add_argument("--threshold", type=int, default=OVER_SIZE_LINES, help="Line count above which a file is flagged (default: 300).")
    args = parser.parse_args()
    if args.heal:
        if ":" not in args.heal:
            print("Error: --heal requires FILE:SYMBOL format.")
            return 1
        file_str, symbol_name = args.heal.split(":", 1)
        file_path = PROJECT_ROOT / file_str
        if not file_path.is_file():
            print(f"Error: {file_path} does not exist.")
            return 1
        heal_file(file_path, symbol_name)
        return 0
    # Audit mode.
    oversized_files = 0
    total_symbols = 0
    for path in iter_source_files(PROJECT_ROOT):
        info = audit_file(path, args.threshold)
        if info is None:
            continue
        rel = path.relative_to(PROJECT_ROOT)
        if not info["oversized"] and not info["classes"] and not info["functions"]:
            continue
        flag = "  <-- oversized" if info["oversized"] else ""
        print(f"\n{rel}: {info['total_lines']} lines, {info['total_bytes']:,} bytes{flag}")
        total_symbols += len(info["classes"]) + len(info["functions"])
        if info["classes"]:
            print("  classes:")
            for cls in info["classes"]:
                print(f"    {cls['name']}: {cls['lines']} lines, {cls['methods']} methods (line {cls['line']})")
        if info["functions"]:
            print("  functions:")
            for fn in info["functions"]:
                print(f"    {fn['name']}: {fn['lines']} lines (line {fn['line']})")
        if info["oversized"]:
            oversized_files += 1
            # Suggest the largest extractable symbols.
            candidates = sorted(
                info["classes"] + info["functions"],
                key=lambda s: s["lines"],
                reverse=True,
            )[:3]
            print("  suggested extracts:")
            for c in candidates:
                mod = suggest_module_name(path, c["name"])
                print(f"    {c['name']} -> {mod}")
    print(f"\n{oversized_files} oversized file(s), {total_symbols} top-level symbol(s) across the codebase.")
    if oversized_files:
        print("Run with --heal FILE:SYMBOL to extract a symbol into its own module.")
        return 1
    print("No oversized files found. Clean.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
