with open(r'E:\Game Installers\0. Steam Game Organizer\services\catalog_service.py', 'rb') as f:
    content = f.read()
    idx = content.find(b'})();\n' + b"'''" + b'\n\n    def _css')
    if idx >= 0:
        print(f'Found at {idx}')
        print(repr(content[idx:idx+60]))
    else:
        print('Not found')
        idx = content.find(b'})();\n' + b"'''")
        if idx >= 0:
            print(f'Found at {idx}')
            print(repr(content[idx:idx+60]))