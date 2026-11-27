r"""
Build the repository's images/ folder:  one resized photo per house, named <listing_id>.jpg
(so images/pbox259649.jpg belongs to the row with listing_id = pbox259649 in data/houses_clean.csv).

The scraper saved every photo of every listing in zim_property_data/images/<listing_id>/0.webp, 1.webp ...
That folder is far too big to submit. This script takes the FIRST available photo of each house (usually the best
exterior shot), shrinks it and saves it as a small JPEG, then adds an `image_file` column to data/houses_clean.csv.

Run from the project root, after the cleaning notebook:

    pip install pandas pillow
    python make_repo_images.py
"""
import argparse, os
import pandas as pd
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("--clean", default=os.path.join("data", "houses_clean.csv"))
ap.add_argument("--raw-dir", default="zim_property_data")
ap.add_argument("--out", default="images")
ap.add_argument("--size", type=int, default=320, help="longest side in pixels")
ap.add_argument("--quality", type=int, default=85)
ap.add_argument("--overwrite", action="store_true", help="re-create images that already exist")
ap.add_argument("--prune", action="store_true", help="delete images in the output folder that do not belong to any house in the CSV (e.g. townhouse photos)")
a = ap.parse_args()

os.makedirs(a.out, exist_ok=True)
houses = pd.read_csv(a.clean, low_memory=False)
ix = pd.read_csv(os.path.join(a.raw_dir, "image_index.csv"))
ix["path"] = ix["path"].astype(str).str.replace("\\", "/", regex=False).map(os.path.normpath)
photos = ix.groupby("listing_id")["path"].apply(list)          # photos of each listing, in gallery order

files, made, kept, failed = [], 0, 0, 0
for n, lid in enumerate(houses["listing_id"].astype(str), 1):
    target = os.path.join(a.out, f"{lid}.jpg")
    if os.path.exists(target) and not a.overwrite:
        files.append(f"{lid}.jpg"); kept += 1; continue
    done = False
    for p in photos.get(lid, []):
        if not os.path.exists(p):
            continue
        try:
            with Image.open(p) as im:
                im = im.convert("RGB"); im.thumbnail((a.size, a.size))
                im.save(target, "JPEG", quality=a.quality, optimize=True)
            done = True; made += 1; break
        except Exception as e:                                  # unreadable file: try the next photo
            print(f"  could not read {p}: {e}")
    files.append(f"{lid}.jpg" if done else "")
    failed += (not done)
    if n % 250 == 0:
        print(f"  {n}/{len(houses)} houses processed")

houses["image_file"] = files
houses.to_csv(a.clean, index=False, encoding="utf-8")
total_mb = sum(os.path.getsize(os.path.join(a.out, f)) for f in files if f) / 1e6
print(f"\n{made} images created, {kept} already existed, {failed} houses have no usable photo.")
print(f"{sum(1 for f in files if f)} files in {a.out}/ ({total_mb:.0f} MB). Column 'image_file' added to {a.clean}.")
# images/ must only contain photos of houses that are in the CSV
wanted = {f for f in files if f}
extras = [f for f in os.listdir(a.out) if f.lower().endswith(".jpg") and f not in wanted]
if extras and a.prune:
    for f in extras:
        os.remove(os.path.join(a.out, f))
    print(f"Pruned {len(extras)} images that do not belong to any house in {a.clean}.")
elif extras:
    print(f"WARNING: {len(extras)} images in {a.out}/ belong to no house in {a.clean} (for example old townhouse photos). "
          "Run again with --prune to delete them (only these small copies are deleted, never your originals).")
if failed:
    print("Houses without a photo (first 10):", houses.loc[houses["image_file"] == "", "listing_id"].head(10).tolist())
