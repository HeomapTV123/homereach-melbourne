# LGA geography audit and first rent map

## Scope and source

Rent: 2025Q3; 2 bedroom flats; 31 LGAs in DFFH's three metropolitan groups.
Map matches one quarter only. The 3,286-row historical rental panel is unchanged.
Boundary archive: LGA_2025_AUST_GDA2020.zip; 40,731,005 bytes.
Boundary SHA-256: `acc3015a0ac78ade978c41a2e4110269b5219b60d6a56cbb70393ae647f31b15`.
ABS source: https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-3-july-2021-june-2026/access-and-downloads/digital-boundary-files/LGA_2025_AUST_GDA2020.zip
ABS definitions: https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-3-july-2021-june-2026/non-abs-structures/local-government-areas
Rental definitions: https://www.dffh.vic.gov.au/publications/rental-report
Licence text in boundary metadata: Unless otherwise noted, content is licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0)

## Boundary inventory

567 national records: 548 spatial records and 19 non-spatial codes.
82 Victorian records: 79 council areas, Unincorporated Vic (29399), and two non-spatial categories.
No usual address (Vic.) (29499) and Migratory - Offshore - Shipping (Vic.) (29799) have null geometry.
The three special Victorian records are excluded from the council lookup, not converted into invented shapes.
Native CRS: GDA2020 / EPSG:7844. Web-map copy: WGS84 / EPSG:4326 using to_crs().
Mapped source geometries: 30 Polygon records and 1 MultiPolygon record. All 31 are non-null, non-empty and valid.
No clipping, dissolving, simplification, buffering or automatic repair is applied.

## Reviewed matching

28 exact name matches within Victoria plus 3 explicitly reviewed aliases; 31/31 matched.
No fuzzy matching. Both publishers' names and the 2025 ABS code are retained.
Name/code matching is a reviewed association, not proof of exactly equivalent geographic definitions.

| Rental-source name | ABS 2025 name | Code | Method |
|---|---|---|---|
| Banyule | Banyule | 20660 | exact_name |
| Bayside | Bayside (Vic.) | 20910 | reviewed_alias |
| Boroondara | Boroondara | 21110 | exact_name |
| Brimbank | Brimbank | 21180 | exact_name |
| Cardinia | Cardinia | 21450 | exact_name |
| Casey | Casey | 21610 | exact_name |
| Darebin | Darebin | 21890 | exact_name |
| Frankston | Frankston | 22170 | exact_name |
| Glen Eira | Glen Eira | 22310 | exact_name |
| Greater Dandenong | Greater Dandenong | 22670 | exact_name |
| Hobsons Bay | Hobsons Bay | 23110 | exact_name |
| Hume | Hume | 23270 | exact_name |
| Kingston | Kingston (Vic.) | 23430 | reviewed_alias |
| Knox | Knox | 23670 | exact_name |
| Manningham | Manningham | 24210 | exact_name |
| Maribyrnong | Maribyrnong | 24330 | exact_name |
| Maroondah | Maroondah | 24410 | exact_name |
| Melbourne | Melbourne | 24600 | exact_name |
| Melton | Melton | 24650 | exact_name |
| Merri-bek | Merri-bek | 24700 | exact_name |
| Monash | Monash | 24970 | exact_name |
| Moonee Valley | Moonee Valley | 25060 | exact_name |
| Mornington Penin'a | Mornington Peninsula | 25340 | reviewed_alias |
| Nillumbik | Nillumbik | 25710 | exact_name |
| Port Phillip | Port Phillip | 25900 | exact_name |
| Stonnington | Stonnington | 26350 | exact_name |
| Whitehorse | Whitehorse | 26980 | exact_name |
| Whittlesea | Whittlesea | 27070 | exact_name |
| Wyndham | Wyndham | 27260 | exact_name |
| Yarra | Yarra | 27350 | exact_name |
| Yarra Ranges | Yarra Ranges | 27450 | exact_name |

## Validation

All 14 original rental fields and all 31 native shapes matched after the attribute join.
Five rejection self-checks passed: unknown name, duplicate lookup, swapped code, missing shape and altered rent.
GeoPackage shapes/attributes, GeoJSON values/shapes and six CSV tables passed read-back checks.
Native inputs, existing notebooks, registry and cleaned rental data stayed unchanged.

## Outputs

- `data/processed/geography/metro_lga_2025.gpkg`: native boundary dimension with 31 features.
- `data/interim/geography/lga_crosswalk_2025.csv`: full reviewed name/code mapping.
- `data/interim/geography/rent_map_2025q3.geojson`: joined map feature data in WGS84.
- `data/interim/geography/rent_map_2025q3.html`: interactive map.
- Other CSVs retain before/after match reports, exclusions, geometry audit and latest attributed rows.

## Interpretation limits

ABS polygons are statistical approximations, not legal boundaries. DFFH group scope is preserved.
Colour represents nominal median AUD/week, not suitability, income-based affordability or available stock.
Larger polygons indicate larger geographic footprints, not more expensive rents or more observations.
Prices vary inside an LGA. Blank space outside mapped polygons is not a zero-rent observation.
Markers are interior label anchors, not rental-property locations or transport stops.
These are historical 2025Q3 statistics, not live listings. Do not apply 2025 shapes to earlier years without review.
Map basemap mode: white-bg. Full boundary detail is retained.
This is a descriptive prototype: no forecasts, routes, transport scores or causal spatial findings are produced.

## References for implementation

- https://geopandas.org/en/stable/docs/user_guide/io.html
- https://geopandas.org/en/stable/docs/user_guide/mergingdata.html
- https://geopandas.org/en/stable/docs/user_guide/projections.html
- https://plotly.com/python/tile-map-layers/
