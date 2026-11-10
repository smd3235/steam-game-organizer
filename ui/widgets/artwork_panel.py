import tkinter as tk
import base64, shutil, subprocess
from services.artwork_service import image_shape
from ui.theme import PANEL2, BORDER, MUTED, ACCENT


class ArtworkPanel(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=PANEL2, highlightbackground=BORDER, highlightthickness=1)
        self.photo = None
        # Reduced padding and more compact loading text
        self.label = tk.Label(self, text="ARTWORK\nLoading…", bg=PANEL2, fg=MUTED, font=("TkDefaultFont", 8, "bold"), justify="center")
        self.label.pack(expand=True, padx=2, pady=2)

    def show(self, result):
        if not result:
            self.label.configure(image="", text="No artwork", compound="center", fg=MUTED)
            return
        candidates = []
        asset_paths = {name: path for name, path in result.assets.items() if path and name not in ("background", "background_raw")}
        # Header image is the canonical banner: prefer it above the primary path and every other asset so a
        # game whose header.jpg CDN URL 404'd (leaving a grid_portrait primary) still shows its banner header
        # from the appdetails asset bundle, not the portrait grid.
        if "header_image" in asset_paths:
            header = asset_paths.pop("header_image")
            if header and header.exists():
                candidates.append(header)
        if result.path:
            candidates.append(result.path)
        # Remaining assets are ordered by banner preference: library_hero is the widest, then capsules,
        # then library_capsule (which may be portrait), then logo and icon. This ensures every horizontal
        # banner-style image is tried before any grid portrait image.
        banner_order = ["library_hero", "capsule_image", "capsule_imagev5", "library_capsule", "library_logo", "icon"]

        def asset_priority(name):
            try:
                return banner_order.index(name)
            except ValueError:
                return len(banner_order)

        ordered_assets = sorted(asset_paths.items(), key=lambda item: asset_priority(item[0]))
        candidates.extend(path for name, path in ordered_assets if path not in candidates)
        # Banner/landscape art (Steam header, library hero, capsule) is preferred over portrait grid art,
        # which is frequently unavailable anyway; fall back to portrait, then anything else.
        banner_candidates = [path for path in candidates if path and path.exists() and not self._is_portrait(path)]
        portrait_candidates = [path for path in candidates if path.exists() and self._is_portrait(path)]
        candidates = banner_candidates or portrait_candidates or [path for path in candidates if path.exists()]
        if not candidates:
            self.label.configure(image="", text="No artwork", compound="center", fg=MUTED)
            return
        for path in candidates:
            if not path or not path.exists():
                continue
            try:
                from PIL import Image, ImageTk

                img = Image.open(path)
                w = self.winfo_width()
                h = self.winfo_height()
                if w < 2:
                    w = self.winfo_reqwidth() or 870
                if h < 2:
                    h = self.winfo_reqheight() or 420
                img.thumbnail((max(20, w - 2), max(20, h - 2)))
                self.photo = ImageTk.PhotoImage(img, master=self)
                self.label.configure(image=self.photo, compound="center", text="", fg=ACCENT)
                return
            except Exception:
                pass
            try:
                self.photo = tk.PhotoImage(file=str(path), master=self)
                self.label.configure(image=self.photo, compound="center", text="", fg=ACCENT)
                return
            except Exception:
                pass
            try:
                ffmpeg = shutil.which("ffmpeg")
                if ffmpeg:
                    converted = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-vf", "scale=230:230:force_original_aspect_ratio=crop", "-f", "image2pipe", "-vcodec", "png", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
                    if converted.returncode == 0 and converted.stdout:
                        self.photo = tk.PhotoImage(data=base64.b64encode(converted.stdout).decode("ascii"))
                        self.label.configure(image=self.photo, compound="center", text="", fg=ACCENT)
                        return
            except Exception:
                pass
        self.label.configure(image="", text=self._why(result, candidates), compound="center", fg=MUTED)

    def _why(self, result, candidates):
        """Name the reason the picture is missing, rather than a flat refusal.

        Every candidate was readable and every decoder was tried and failed, so the cause is the toolchain,
        not the file. Saying so is the difference between a person installing Pillow and a person concluding
        the artwork never downloaded - which is what a bare "could not be rendered" told them.

        The result.reason field describes where the artwork came from ("Cache hit", "Downloaded from …"),
        not why it cannot be displayed, so it is deliberately not returned here: a cached JPEG that Pillow
        cannot decode would otherwise show "Cache hit" as its error text.
        """
        try:
            import PIL  # noqa: F401
        except ImportError:
            return "No image decoder\nNeeds Pillow\npip install pillow"
        return "Artwork failed"

    def _is_portrait(self, path):
        return image_shape(path) is True
