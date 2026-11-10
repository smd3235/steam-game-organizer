from pathlib import Path
import os

def is_link(path):
    """True for anything the operating system resolves to somewhere else: a symlink, or a Windows junction,
    directory reparse point, or symlink. Path.is_symlink() is not enough on its own - it reports False for a
    junction, because a junction is a reparse point the OS hands back as an ordinary directory - and os.walk()
    follows a junction even with followlinks=False, since it only consults that same answer.

    Cleanup needs this more than a scan does. A scan that follows a junction wastes work and misreports, but
    a deletion that follows one removes files in a tree the caller was never given: os.walk() descends into
    the junction, matches a temp name in the *other* folder, and unlinks it. Syncthing sets junctions up
    routinely, so this is not a contrived shape.
    """
    try:
        if Path(path).is_symlink(): return True
    except OSError:
        return True
    if hasattr(os.path,'isjunction'):
        try:
            if os.path.isjunction(path): return True
        except OSError:
            return True
    else:
        # Python before 3.12 has no os.path.isjunction, so read the attribute the win32 layer sets instead.
        try:
            return bool(getattr(os.lstat(path),'st_file_attributes',0)&0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
        except (OSError,AttributeError):
            return True
    return False

def walk_files(root):
    """Every file under root, without descending twice into the same directory.

    Path.rglob('*') follows a Windows junction or a Linux bind mount, because the operating system resolves one
    as an ordinary directory and scandir is handed nothing that says otherwise. A junction inside a library
    that pointed back at the library made a library holding one game scan as 64 archives - one per level that
    still fitted inside MAX_PATH, which is the only reason it stopped - and Organize then treated all 64 as
    copies of one another, so the real game was filed under Archive/ as a duplicate of itself and the library
    was left holding Loop/Loop/Loop/... all the way down. On a filesystem without that path-length limit the
    walk has no way to end at all.

    Directories are compared by resolved path and one already visited is not descended into again, which closes
    the cycle wherever it is. A symlink needs no case of its own: by the time it is reached it resolves to a
    directory the walk has already been through.
    """
    seen=set()
    stack=[Path(root)]
    while stack:
        current=stack.pop()
        try:
            resolved=current.resolve()
        except OSError:
            continue
        if resolved in seen: continue
        seen.add(resolved)
        try:
            entries=sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(): stack.append(entry)
                else: yield entry
            except OSError:
                continue
