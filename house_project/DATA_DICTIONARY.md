# Data dictionary

Source: listings scraped from https://www.property.co.zw (asking prices for properties **for sale**). Each row is one listing. `date_collected` records the day it was scraped (22–25 November 2026).

| File | What it is |
| `data/listings_raw.csv` | Everything collected: 6,035 listings of all property types (houses, townhouses, flats, land, commercial), exactly as scraped. |
| `data/all_listings_deduped.csv` | The same after removing duplicates, with `price_usd`, `city_clean` and `area_clean` added. |
| `data/houses_clean.csv` | **The modelling set**: cleaned houses only (one row per house; townhouses, flats and land are excluded). Described below. |
| `images/<listing_id>.jpg` | One photo per house (the first gallery photo, shrunk to 320 px). The file name is the `listing_id` of the row it belongs to. |

## `data/houses_clean.csv`

### Identifiers and dates
| Column | Description |
|---|---|
| `listing_id` | The site's listing code (agency prefix + number, for example `pbox259649`). Unique. The photo for this house is `images/<listing_id>.jpg`. |
| `listing_url` | Web address of the listing. |
| `title` | The advert's headline. |
| `property_type_url` | Property type taken from the listing address. Always `houses` in this file (townhouses, flats and land are not modelled). |
| `date_posted` | Date the advert was first posted on the site. |
| `date_collected` | Date the listing was scraped. |
| `listing_age_days` | Days between `date_posted` and `date_collected`. |
| `agent_name` | The estate agency that placed the advert. |

### Target
| Column | Description |
|---|---|
| `price_usd` | **Asking price in US dollars.** The variable to predict. |
| `log_price` | Natural logarithm of `price_usd`. |
| `price_outlier_flag` | 1 if `log_price` is more than 1.5 interquartile ranges outside the quartiles for its city (flagged, not removed). |

### Location
| Column | Description |
|---|---|
| `city_clean` | `Harare`, `Bulawayo`, `Chitungwiza` or `Other` (all other towns and rural areas). |
| `area_clean` | Region within the city (for example `Harare North`, `Harare West`, `Harare High Density`) or, outside the big cities, the town or province. |
| `suburb` | Suburb name as shown on the site. |
| `suburb_grouped` | `suburb`, with suburbs that have fewer than 10 houses grouped as `Other`. |
| `latitude`, `longitude` | Map coordinates of the listing. Where the listing has no map pin, or the pin is outside Zimbabwe (an error), the average for the same suburb (then area, then city). |

### Size and rooms
| Column | Description |
|---|---|
| `bedrooms` | Number of bedrooms (1–12). |
| `bathrooms` | Number of bathrooms (1–12). |
| `garages` | Number of garages. Set to 0 when the advert does not mention one. |
| `floor_size_m2` | Floor (building) area in square metres, 25–4,000. |
| `land_size_m2` | Stand (plot) size in square metres, 50–100,000. |

### Missing-value indicators (1 = the value was filled in, 0 = recorded on the site)
| Column | Description |
|---|---|
| `garages_not_stated` | The advert did not state a garage count (`garages` was set to 0). |
| `bathrooms_imputed` | `bathrooms` was missing or invalid; filled with the median for houses with the same number of bedrooms. |
| `floor_size_m2_imputed` | `floor_size_m2` was missing or invalid; filled with the median for the same city and number of bedrooms. |
| `land_size_m2_imputed` | `land_size_m2` was missing or invalid; filled with the median for the same area. |
| `latitude_imputed` | The coordinates (`latitude` and `longitude`) are suburb averages, not the listing's own pin. |

### Amenities and text
| Column | Description |
|---|---|
| `amenities` | The amenities list as scraped, separated by `\|` (blank if none were listed). |
| `amenities_listed` | 1 if the advert listed any amenities, 0 if not. |
| `n_amenities` | Number of amenities listed. |
| `description` | The agent's description of the property, as written (input for the text model). |
| `desc_words` | Number of words in `description`. |
| `image_file` | File name of the house's photo in `images/` (blank if no photo could be downloaded). |
| `n_photos` | Number of photos the scraper downloaded for the house (the repository keeps one, in `images/`). |

### Amenity indicators (0/1, from the structured `amenities` list)
Created for every amenity present in at least 3% of houses (36 of the 46 different amenities seen): `amen_main_en_suite`, `amen_walled`, `amen_fitted_kitchen`, `amen_borehole`, `amen_verandah`, `amen_tiled`, `amen_good_zesa`, `amen_garden`, `amen_water_tank`, `amen_municipal_water`, `amen_garage`, `amen_paved`, `amen_sewer_system`, `amen_fireplace`, `amen_staff_quarters`, `amen_entertainment_area`, `amen_flatlet_cottage`, `amen_internet_connection`, `amen_solar_system`, `amen_carport`, `amen_electric_gate`, `amen_swimming_pool`, `amen_study_office`, `amen_main_road_frontage`, `amen_storage_room`, `amen_access_control`, `amen_double_storey`, `amen_24hr_security`, `amen_electric_fence`, `amen_burglar_alarm`, `amen_intercom_system`, `amen_air_conditioning`, `amen_cctv_surveillance`, `amen_wheelchair_accessibility`, `amen_split_level`, `amen_wooden_floor`.
A value of 0 means the amenity was not listed (it may still exist: 20% of houses list no amenities at all, see `amenities_listed`).

### Keyword indicators (0/1, from the title, description and amenities text)
1 if the text mentions the feature, otherwise 0. These pick up features that agents mention in the description even when the amenities list is empty.

| Column | Matches text such as |
|---|---|
| `flag_borehole` | borehole |
| `flag_solar` | solar |
| `flag_pool` | swimming pool, pool |
| `flag_cottage` | cottage, flatlet, granny flat |
| `flag_walled` | walled, perimeter wall |
| `flag_gated` | gated, electric gate, security gate |
| `flag_electric_fence` | electric fence |
| `flag_title_deeds` | title deeds, freehold |
| `flag_cession` | cession |
| `flag_ensuite` | en-suite |
| `flag_tiled` | tiled |
| `flag_fitted_kitchen` | fitted kitchen |
| `flag_staff_quarters` | staff quarters, servants |
| `flag_garden` | garden |
| `flag_alarm` | alarm |
| `flag_backup_power` | generator, inverter, backup power |
| `flag_water_tank` | water tank, jojo, tank |
| `flag_cluster_or_complex` | cluster, complex, townhouse |
| `flag_double_storey` | double storey |
| `flag_needs_work` | incomplete, unfinished, under construction, dilapidated, renovation |
| `flag_commercial_use` | commercial, clinic, guest house |
| `flag_garage` | garage, carport |
| `flag_fireplace` | fireplace |
| `flag_verandah` | veranda |
| `flag_study` | study, home office |

## `data/listings_raw.csv` (collected data, before cleaning)

Same meaning as above, with these differences: `category` is the section of the site the link was found in; `price_raw` is the price as displayed (for example `$670,000` or `P.O.A.`); `price_value` and `currency` are the number and currency parsed from it; `location_raw` is the full location text (`suburb`, `area` and `city` are its first, second and third parts); `reference` is the site's reference code; `n_images_found` and `image_urls` list the photos available on the listing page; `latitude`, `longitude`, `bedrooms`, `bathrooms`, `floor_size_m2` and `land_size_m2` are unfiltered and contain impossible values that the cleaning notebook removes; `flag_*` columns are the keyword indicators above.
