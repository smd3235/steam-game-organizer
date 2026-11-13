"""Extracted from steam_game_organizer.py.

    _handle_open_folder_uri was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from core.constants import APP_NAME


def _handle_open_folder_uri(uri, config, logger):
    """Opens the game folder in Explorer/Files.

    A file:// page cannot open a folder, so this goes through the same
    steamgameorganizer:// protocol handler as Extract. The path is validated
    against the library root by parse_open_folder_uri, so a malicious page
    can only ask for a folder the user already owns.
    """
    from core.uri_actions import UriRefused, parse_open_folder_uri

    try:
        folder = parse_open_folder_uri(uri, config.library_root)
    except UriRefused as refused:
        logger.warning("EXTRACT", f"URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]")
        print(f"{APP_NAME}: {refused}")
        return 2
    logger.info("EXTRACT", f"URI_ACCEPTED action=open-folder path=[{folder}]")
    try:
        import os

        os.startfile(str(folder))
    except OSError as exc:
        print(f"{APP_NAME}: Could not open {folder}: {exc}")
        return 1
    return 0
