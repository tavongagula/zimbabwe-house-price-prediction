# Asking prices of houses for sale in Zimbabwe: structured features, photos and text

Deep learning course project · Tavonga Mangundhla, University of Zimbabwe · HDSC R236667S

**Research question.** Which features explain the asking prices of houses for sale in Zimbabwe, and how accurately can a model predict them?

I collected 6,035 for-sale listings from https://www.property.co.zw (22 to 25 November 2026), cleaned them into 2,283 houses, and compared a linear-regression baseline with ridge regression, gradient boosting and neural networks that also use the house photos (a pretrained CNN) and the advert text (a pretrained sentence transformer). The written report is `report.pdf` (6 pages).

## Results in brief

| Model | Test RMSE (log price) | Test R² (log price) | Typical error | 5-fold CV RMSE (log) |
|---|---|---|---|---|
| Linear regression (baseline) | 0.462 | 0.793 | 23.8% | 0.490 |
| Ridge, all structured features | 0.366 | 0.870 | 18.9% | 0.367 |
| Neural net + photos | 0.305 | 0.910 | 17.4% | 0.351 |
| Multimodal neural net (structured + photos + text) | 0.308 | 0.908 | 17.4% | 0.353 |

"Typical error" is the median absolute percentage error. The test set has 343 houses, so differences of about 0.01 to 0.02 between the better models are within noise; see the report. Full tables are in `tables/`.

## What is in this repository

```
README.md                          this file
report.pdf                         the report (max. 6 pages)
requirements.txt                   Python packages
.gitignore

data/
  listings_raw.csv                 all 6,035 collected listings, as scraped
  all_listings_deduped.csv         every property type after removing duplicates
  houses_clean.csv                 THE MODELLING SET: 2,283 cleaned houses (key column: listing_id)
  DATA_DICTIONARY.md               short data dictionary for the CSV files
  image_features.npz               photo features (frozen ResNet-50, mean of up to 5 photos per house)
  text_features.npz                description features (frozen MiniLM sentence embeddings, prices masked)
  test_predictions.csv             predictions of every model for the 343 test houses
images/
  <listing_id>.jpg                 one small photo per house; the file name is the listing_id in the CSV

02_cleaning_and_exploration.ipynb  cleaning and exploration (tables and plots)
03_models.ipynb                    baseline, neural networks, evaluation, residual checks, feature importance
tables/, figures/                  the tables and plots produced by the notebooks

property_scraper.py                data collection (step 1)
extract_features.py, text_utils.py photo and text features for the networks (run once)
make_repo_images.py                builds images/ from the full-size photos
```

**How images and the CSV are linked.** `data/houses_clean.csv` has a `listing_id` column (for example `pbox259649`) and an `image_file` column. The photo of that house is `images/pbox259649.jpg`. A house with a blank `image_file` had no photo that could be downloaded.

**Not included.** The raw scraper output (`zim_property_data/`: the raw HTML pages and every full-size photo) is several gigabytes. The notebooks do not need it: `02` falls back to `data/listings_raw.csv`, and `03` uses the saved feature files.

## Quick start: re-run the analysis (no scraping, about 30 minutes)

Needs Python 3.10 or newer. The internet is only needed to install packages.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate        Mac/Linux:  source .venv/bin/activate
pip install -r requirements.txt
jupyter notebook
```

Open the notebooks from the repository folder and choose **Kernel → Restart & Run All**, in this order:

1. **`02_cleaning_and_exploration.ipynb`** (about 1 to 2 minutes). Reads `data/listings_raw.csv` and rewrites `data/houses_clean.csv`, `data/all_listings_deduped.csv`, `tables/` and `figures/`.
2. **`03_models.ipynb`** (typically 10 to 30 minutes on a laptop CPU). Reads `data/houses_clean.csv` and the two feature files. For a quick check that it runs, set `QUICK = True` in the settings cell (about 2 minutes, one seed, no cross-validation, so the numbers are not final). Set it back to `False` for the results in the report.

`03_models.ipynb` needs PyTorch for the neural networks. Without it, models 1 to 4 (linear, ridge, gradient boosting, ridge with photo and text features) still run and the neural networks are skipped with a message.

If a notebook says it cannot find the project folder, start Jupyter from the repository folder, or set `PROJECT_ROOT` in the first code cell.

### Reproducibility notes
* The train / validation / test split and all random seeds are fixed (seed 42), so the split and the linear, ridge and boosting results should reproduce exactly.
* The neural networks are averages of 5 seeds; small differences (in the third decimal) between machines and PyTorch versions are normal.
* The text features were made from descriptions with amounts of money masked (see `text_utils.py`), because many adverts quote the asking price.

## Optional: reproduce the data collection from scratch

This takes many hours and the website changes daily, so a new run will collect a different set of listings. It needs the internet, and the full-size photos need several gigabytes of disk space. Replace the e-mail address with your own: it is sent to the website in the request header.

```bash
# 1. collect the listing links (houses, townhouses, flats, land and other for-sale categories)
python property_scraper.py discover --by-location --auto-categories --contact your.email@example.com
# 2. scrape every listing (about 4 seconds per listing)
python property_scraper.py details --contact your.email@example.com
# 3. download the photos (all photos for houses, 2 for other types)
python property_scraper.py images --category house --max-images 1000 --contact your.email@example.com
python property_scraper.py images --exclude-category house --max-images 2 --contact your.email@example.com
# 4. clean the data: run 02_cleaning_and_exploration.ipynb
# 5. one small photo per house for the repository
python make_repo_images.py --prune
# 6. photo and text features for the networks (downloads two pretrained models the first time)
python extract_features.py
# 7. run 03_models.ipynb
```

`python property_scraper.py probe <url> --contact ...` tests the parser on one page.

## Responsible data collection

The scraper reads `robots.txt` and skips anything it disallows, waits several seconds between page requests (about one second between photo downloads), identifies itself with a contact address, retries politely and stops if the site refuses requests. The collection date is recorded for every listing (`date_collected`). **[FILL IN: confirm that you read the website's terms of use.]** The listing text and photos belong to the website and its agents. They are included in this repository only for marking this coursework and must not be republished.

## Limitations (details in the report)
These are asking prices, not sale prices; the data are a four-day snapshot; the dataset is small for deep learning; photos are not standardised and many carry the agency's watermark; about half of the map coordinates are suburb averages.
