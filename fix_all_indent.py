with open(r'E:\Game Installers\0. Steam Game Organizer\tests\test_regressions.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix remaining indentation issues in the file
for i in range(len(lines)):
    line = lines[i]
    stripped = line.lstrip()
    if not stripped:
        continue
    leading = len(line) - len(stripped)
    
    # Class definitions at 0 or 1 space -> 0 spaces
    if stripped.startswith('class '):
        if leading > 0:
            lines[i] = stripped
    # Method definitions at 2 spaces (class level)
    elif stripped.startswith('def '):
        if leading != 2:
            lines[i] = '  ' + stripped
    # Docstrings right after class - should be 2 spaces
    elif stripped.startswith('"""') and i > 0:
        prev = lines[i-1].strip()
        if prev.startswith('class ') or prev.startswith('def '):
            if leading != 2:
                lines[i] = '  ' + stripped
    # Method bodies - 6 spaces
    elif leading in (3, 4, 5) and not stripped.startswith('#'):
        lines[i] = ' ' * 6 + stripped
    # Lines at 2 spaces that aren't def/class - should be 6
    elif leading == 2 and not stripped.startswith('def ') and not stripped.startswith('class '):
        lines[i] = ' ' * 6 + stripped

with open(r'E:\Game Installers\0. Steam Game Organizer\tests\test_regressions.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('Done')