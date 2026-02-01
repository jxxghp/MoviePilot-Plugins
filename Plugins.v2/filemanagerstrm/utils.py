import os
import shutil

META_EXTS = (".jpg", ".png", ".nfo", ".srt", ".ass", ".ssa", ".webp")
STRM_EXT = ".strm"

def is_meta_only(files):
    return files and all(f.lower().endswith(META_EXTS) for f in files)

def has_strm(files):
    return any(f.lower().endswith(STRM_EXT) for f in files)

def is_final_media_dir(path):
    items = os.listdir(path)
    files = [f for f in items if os.path.isfile(os.path.join(path, f))]
    dirs = [d for d in items if os.path.isdir(os.path.join(path, d))]
    return not dirs and is_meta_only(files)

def scan_missing_strm(root):
    result = []
    for cur, dirs, files in os.walk(root):
        if is_final_media_dir(cur) and not has_strm(files):
            result.append(cur)
    return result

def find_in_full_lib(target, full_root, src_root):
    rel = os.path.relpath(target, start=src_root)
    candidate = os.path.join(full_root, rel)
    return candidate if os.path.exists(candidate) else None

def copy_with_structure(src, src_root, dst_root):
    rel = os.path.relpath(src, src_root)
    dst = os.path.join(dst_root, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if not os.path.exists(dst):
        shutil.copytree(src, dst)
