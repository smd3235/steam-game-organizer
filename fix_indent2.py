with open(r'E:\Game Installers\0. Steam Game Organizer\tests\test_regressions.py', 'rb') as f:
    content = f.read()

# Fix the indentation issue - replace the problematic sequence
old = b")\n\r\n def test_the_plan_builds_the_layout"
new = b")\r\n\r\n  def test_the_plan_builds_the_layout"
content = content.replace(old, new)

with open(r'E:\Game Installers\0. Steam Game Organizer\tests\test_regressions.py', 'wb') as f:
    f.write(content)
print('Done')