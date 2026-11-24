"""Artwork panel on the Review screen — shows the matched game's Steam artwork
(primary hero/grid logo/icon) with fallback to placeholder text."""

from __future__ import annotations

import customtkinter as ctk
import tkinter as tk
import base64, shutil, subprocess
from PIL import Image
from services.artwork_service import image_shape
from ui.theme import PANEL2, BORDER, MUTED, ACCENT, Theme, CTkFrame, CTkLabel


class ArtworkPanel(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=PANEL2, border_color=BORDER, border_width=1)
        self.photo = None
        # Reduced padding and more compact loading text
        self.label = CTkLabel(self, text="ARTWORK\nLoading…", fg_color=PANEL2, text_color=MUTED, font=("TkDefaultFont", 8, "bold"), justify="center")
        self.label.pack(expand=True, padx=2, pady=2)

    def show(self, result):
        if not result:
            self.label.configure(image="", text="No artwork", compound="center", text_color=MUTED)
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
            self.label.configure(image="", text="No artwork", compound="center", text_color=MUTED)
            return
        for path in candidates:
            if not path or not path.exists():
                continue
            try:
                img = Image.open(path)
                w = self.winfo_width()
                h = self.winfo_height()
                if w < 2:
                    w = self.winfo_reqwidth() or 870
                if h < 2:
                    h = self.winfo_reqheight() or 420
                img.thumbnail((max(20, w - 2), max(20, h - 2)))
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                self.photo = ctk_img
                self.label.configure(image=self.photo, compound="center", text="", text_color=ACCENT)
                return
            except Exception:
                pass
            try:
                ffmpeg = shutil.which("ffmpeg")
                if ffmpeg:
                    converted = subprocess.run([ffmpeg, "-v", "error", "-i", str(path),
                        "-vf", "scale=230:230:force_original_aspect_ratio=crop",
                        "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                        check=False)
                    if converted.returncode == 0 and converted.stdout:
                        ctk_img = ctk.CTkImage(light_image=Image.open(__import__('io').BytesIO(converted.stdout)),
                                               dark_image=Image.open(__import__('io').BytesIO(converted.stdout)),
                                               size=(230, 230))
                        self.photo = ctk_img
                        self.label.configure(image=self.photo, compound="center", text="", text_color=ACCENT)
                        return
            except Exception:
                pass
        self.label.configure(image="", text=self._why(result, candidates), compound="center", text_color=MUTED)

    def _why(self, result, candidates):
        """Name the reason the picture is missing, rather than a flat refusal.

        Every candidate was readable and every decoder was tried and failed, so the cause is the toolchain,
        not the file.

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