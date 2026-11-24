with open('ui/scan_view.py') as f:
    content = f.read()
content = content.replace(
    'self.scan_btn = CTkButton(conv_row, text="Scan + Artwork", command=self.scan_new_artwork,',
    'self.art_btn = CTkButton(conv_row, text="Scan & Artwork", command=self.on_scan_artwork,'
)
with open('ui/scan_view.py', 'w') as f:
    f.write(content)
print('Done')