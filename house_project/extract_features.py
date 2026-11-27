r"""
Extract frozen, pretrained features for the multimodal model.   Run ONCE from the project folder (C:\house_project):

    pip install torch torchvision sentence-transformers pillow numpy pandas
    python extract_features.py

Needs internet the first time only (to download the pretrained models, roughly 100-200 MB); afterwards it works offline.

Reads   data/houses_clean.csv
        zim_property_data/image_index.csv and the ORIGINAL photos in zim_property_data/images/<listing_id>/
Writes  data/image_features.npz   one row per house: mean ResNet-50 feature vector (2048 numbers) over up to 5 photos
        data/text_features.npz    one row per house: MiniLM sentence embedding (384 numbers) of title + description,
                                  with amounts of money masked out (the price must not leak into the text features)

03_models.ipynb loads these two small files, so the notebook can be re-run without the photos.
"""
import argparse, os, time
import numpy as np
import pandas as pd

from text_utils import mask_prices


# ----------------------------------------------------------------------------- photos
def photo_paths_by_listing(data_dir, ids, max_photos):
    """The first `max_photos` photos that exist on disk for each listing, in gallery order."""
    ix = pd.read_csv(os.path.join(data_dir, "image_index.csv"))
    ix["path"] = ix["path"].astype(str).str.replace("\\", "/", regex=False).map(os.path.normpath)
    groups = ix.groupby("listing_id")["path"].apply(list)
    return {lid: [p for p in groups.get(lid, []) if os.path.exists(p)][:max_photos] for lid in ids}


def extract_images(paths_by_id, embed_batch, batch_size=32):
    """Mean feature vector per listing. embed_batch(paths) -> list with one vector (or None if unreadable) per path."""
    ids = list(paths_by_id)
    pairs = [(i, p) for i, lid in enumerate(ids) for p in paths_by_id[lid]]
    sums, counts, t0 = None, np.zeros(len(ids), dtype=int), time.time()
    for start in range(0, len(pairs), batch_size):
        chunk = pairs[start:start + batch_size]
        for (i, _), v in zip(chunk, embed_batch([p for _, p in chunk])):
            if v is None:
                continue
            if sums is None:
                sums = np.zeros((len(ids), len(v)), dtype=np.float64)
            sums[i] += v
            counts[i] += 1
        done = start + len(chunk)
        if (start // batch_size) % 20 == 0 or done == len(pairs):
            rate = done / max(time.time() - t0, 1e-6)
            print(f"  {done}/{len(pairs)} photos | {rate:.1f} photos/s | about {(len(pairs) - done) / rate / 60:.0f} min left")
    if sums is None:
        raise SystemExit("No photos could be read. Check zim_property_data/image_index.csv and the images folder.")
    feats = np.divide(sums, counts[:, None], out=np.zeros_like(sums), where=counts[:, None] > 0)
    return ids, feats.astype(np.float32), counts


def make_image_embedder():
    import torch
    from PIL import Image
    from torchvision import models
    torch.set_num_threads(os.cpu_count() or 1)
    weights = models.ResNet50_Weights.IMAGENET1K_V2
    net = models.resnet50(weights=weights)
    net.fc = torch.nn.Identity()          # keep the 2048-number summary of the photo, drop the ImageNet classifier
    net.eval()
    preprocess = weights.transforms()     # resize to 232, centre-crop 224, normalise the way the model was trained

    def embed(paths):
        tensors, keep = [], []
        for k, p in enumerate(paths):
            try:
                with Image.open(p) as im:
                    tensor = preprocess(im.convert("RGB"))
                tensors.append(tensor)
                keep.append(k)
            except Exception as e:                 # unreadable photo: skip it, the house keeps its other photos
                print(f"  could not read {p}: {e}")
        out = [None] * len(paths)
        if tensors:
            with torch.no_grad():
                feats = net(torch.stack(tensors)).numpy()
            for k, v in zip(keep, feats):
                out[k] = v
        return out
    return embed


# ----------------------------------------------------------------------------- text
def text_for(houses):
    return (houses["title"].fillna("") + ". " + houses["description"].fillna("")).map(mask_prices).tolist()


def make_text_embedder():
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return lambda texts: model.encode(texts, batch_size=64, show_progress_bar=True, normalize_embeddings=True)


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", default=os.path.join("data", "houses_clean.csv"))
    ap.add_argument("--data-dir", default="zim_property_data")
    ap.add_argument("--out-dir", default="data")
    ap.add_argument("--max-photos", type=int, default=5, help="photos averaged per house")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--limit", type=int, default=0, help="only the first N houses (for a quick test)")
    ap.add_argument("--skip-images", action="store_true")
    ap.add_argument("--skip-text", action="store_true")
    a = ap.parse_args()

    houses = pd.read_csv(a.clean, low_memory=False)
    if a.limit:
        houses = houses.head(a.limit)
    ids = houses["listing_id"].astype(str).tolist()
    os.makedirs(a.out_dir, exist_ok=True)

    if not a.skip_images:
        print(f"Photos: up to {a.max_photos} per house for {len(ids)} houses (ResNet-50, first run downloads the model)")
        paths = photo_paths_by_listing(a.data_dir, ids, a.max_photos)
        print(f"  {sum(len(v) for v in paths.values())} photos found; {sum(1 for v in paths.values() if not v)} houses have none")
        out_ids, feats, counts = extract_images(paths, make_image_embedder(), a.batch_size)
        np.savez_compressed(os.path.join(a.out_dir, "image_features.npz"), ids=np.array(out_ids, dtype=str), features=feats, n_used=counts)
        print(f"  saved {feats.shape} -> {os.path.join(a.out_dir, 'image_features.npz')}")

    if not a.skip_text:
        print("Text: sentence embeddings of title + description (prices masked)")
        feats = np.asarray(make_text_embedder()(text_for(houses)), dtype=np.float32)
        np.savez_compressed(os.path.join(a.out_dir, "text_features.npz"), ids=np.array(ids, dtype=str), features=feats)
        print(f"  saved {feats.shape} -> {os.path.join(a.out_dir, 'text_features.npz')}")
    print("Done.")


if __name__ == "__main__":
    main()
