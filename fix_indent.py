with open(r'E:\Game Installers\0. Steam Game Organizer\tests\test_regressions.py', 'rb') as f:
    content = f.read()

# Fix the indentation issue
old = b" answer was not kept ({found}, {reason})')\r\n\r\n def test_the_plan_builds_the_layout"
new = b" answer was not kept ({found}, {reason})')\r\n\r\n  def test_the_plan_builds_the_layout"
content = content.replace(old, new)

with open(r'E:\Game Installers\0. Steam Game Organizer\tests\test_regressions.py', 'wb') as f:
    f.write(content)
print('Done')