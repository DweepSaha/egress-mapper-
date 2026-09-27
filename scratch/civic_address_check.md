# Civic address cross-check (read-only validation)

Mapped-building counts compared with each province's own civic address points. Addresses are not buildings; NS and NB files are maintained independently and are not one series. Neighbourhoods are the frozen engine's own.

## Nova Scotia - NSCAF Civic Points (Upper Tantallon)
Source: Service Nova Scotia, *Nova Scotia Civic Address File - Civic Points* (data.novascotia.ca tntn-er5g), rows updated 2026-09-05 (monthly), Nova Scotia Open Government Licence. Exported WGS84; reprojected to EPSG:2953. Downloaded with the portal's within_box filter on the study box.
Attributes: pntid, segid, civicnum, civsuffix, unit_num, add_loc, strprefix/strname/strsuffix/strdir, comm_id, comm, mun, county, lat, long. **No residential/commercial (land-use) attribute.** `add_loc` records how the point was placed (building centroid vs approximate parcel location, utility, fire water source ...).
- Civic points inside the study box: **25,914** (mapped buildings >= 40 m2 in the same box: OSM 23,979, Microsoft 18,985)
- By `kind`: Building Centroid 23,691, Approx. Location on Parcel - XY unknown 2,163, Utility 35, Fire Dept Water Source 12, Other 7, Building Entrance 2, Unknown 2, Public Place 1, Address Location for Multi-Unit 1
- Attached to a road within 150 m: 24,834; not attached (>150 m from any road): 1,080
- unit_num populated: 0 (one point per civic number; units are not listed)

### WESTWOOD HILLS (nid 99)
- **OSM 751 | Microsoft 680 | NS civic addresses 717** (attached like-for-like; 685 of them placed at a building centroid/entrance) | inside the 40 m footprint: 235
- By placement: Building Centroid 685, Approx. Location on Parcel - XY unknown 32
- The province's count falls **between Microsoft and OSM**.

### Largest Tantallon neighbourhoods
| nid | status | OSM mapped bldgs | Microsoft mapped bldgs | civic (attach, like-for-like) | civic (in 40 m footprint) |
|---|---|---|---|---|---|
| 117 | red | 1,666 | 1,486 | **2,183** | 865 |
| 121 | red | 1,219 | 1,015 | **1,193** | 555 |
| 20 | not_assessed | 917 | 832 | **800** | 531 |
| 58 | red | 860 | 829 | **800** | 257 |
| 99 | red | 751 | 680 | **717** | 235 |
| 11 | not_assessed | 746 | 546 | **783** | 769 |
| 135 | not_assessed | 687 | 642 | **725** | 718 |
| 155 | not_assessed | 672 | 624 | **938** | 934 |
| 115 | red | 541 | 483 | **527** | 294 |
| 101 | not_assessed | 540 | 452 | **523** | 198 |
| 12 | not_assessed | 533 | 503 | **567** | 567 |
| 191 | not_assessed | 488 | 10 | **594** | 153 |
| 6 | not_assessed | 364 | 148 | **355** | 358 |
| 161 | not_assessed | 351 | 29 | **389** | 344 |
| 114 | red | 325 | 316 | **299** | 171 |
- Across 28 assessed neighbourhoods: civic/OSM median 0.94, civic/Microsoft median 1.07; civic between OSM and Microsoft in 8 of 28

## New Brunswick - Address NB Civic Address Database (Fredericton, Pointe-Sapin)
Source: Service New Brunswick / GeoNB, *Address NB Civic Address Database* (geonb_anb.gdb; source: Department of Public Safety), file readme dated 2024-04-23, GeoNB / NB Open Government Licence. Native EPSG:2953 (no reprojection). Read with a study-box bbox filter; the province was never loaded.
Layer `geonb_anb_addresses` (civic addresses; a separate `geonb_anb_subaddresses` layer lists units). Attributes: CIV_ID, ADDR_SYM, ADDR_DESC, CIVIC_NUM, NUM_SUFFIX, PID, STREET, ST_TYPE_E, ST_TYPE_F, RD_SIDE_E, RD_SIDE_F, ST_DIR_E, ST_DIR_F, COMMUNITY, COUNTY, ADD_TYPE_E, ADD_TYPE_F, DESCRIPT, STRUCT_E, STRUCT_F, STRU_NAME, ALT_ACCESS, COLL_MTHD, CREATED, MODIFIED, LATITUDE, LONGITUDE, SUB_COUNT
**Residential vs commercial: yes** - `STRUCT_E` (structure type: Residence, Cottage / Camp, Commercial / Business, Non-Commercial, Tower Site ...). Residential-only counts below use STRUCT_E = 'Residence'; cottages/camps are reported separately (seasonal).

### Pointe-Sapin
- Civic points inside the study box: **1,907** (mapped buildings >= 40 m2 in the same box: OSM 147, Microsoft 1,540)
- By `kind`: Residence 1,589, Commercial / Business 101, (not tagged) 92, Cottage / Camp 86, Non-Commercial 34, Tower Site 4, Pay Phone / Phone Booth 1
- Attached to a road within 150 m: 1,738; not attached (>150 m from any road): 169
- Address type (ADD_TYPE_E): Parcel 1,869, Driveway 38
- Multi-unit: 14 addresses carry sub-addresses (units), 57 units in total (counted once here, as one civic address each). Latest record MODIFIED date in the box: 2024-04-03
- Residential (STRUCT_E = Residence): **1,589**; Cottage / Camp: 86
- **POINTE-SAPIN (whole study box): OSM 147 | Microsoft 1,540 | NB civic addresses 1,907 (Residence 1,589; Residence + Cottage/Camp 1,675)**
- The documented 160 / 1,737 are ALL footprints in the Pointe-Sapin files; the engine analyses footprints >= 40 m2, which is 147 / 1,540 in the same box. Both comparisons are shown.
| nid | status | OSM mapped bldgs | Microsoft mapped bldgs | civic (attach, like-for-like) | civic (in 40 m footprint) | civic residential (attach) |
|---|---|---|---|---|---|---|
| 6 | not_assessed | 0 | 144 | **189** | 134 | 177 |
| 53 | not_assessed | 0 | 49 | **56** | 40 | 53 |

### Fredericton
- Civic points inside the study box: **45,130** (mapped buildings >= 40 m2 in the same box: OSM 29,088, Microsoft 32,926)
- By `kind`: Residence 41,867, (not tagged) 2,363, Commercial / Business 578, Non-Commercial 221, Cottage / Camp 74, Tower Site 22, End of Designation 4, Intersection 1
- Attached to a road within 150 m: 44,676; not attached (>150 m from any road): 454
- Address type (ADD_TYPE_E): Parcel 43,325, Driveway 1,654, Other 151
- Multi-unit: 1,779 addresses carry sub-addresses (units), 14,546 units in total (counted once here, as one civic address each). Latest record MODIFIED date in the box: 2024-04-19
- Residential (STRUCT_E = Residence): **41,867**; Cottage / Camp: 74
| nid | status | OSM mapped bldgs | Microsoft mapped bldgs | civic (attach, like-for-like) | civic (in 40 m footprint) | civic residential (attach) |
|---|---|---|---|---|---|---|
| 0 | amber | 826 | 664 | **882** | 799 | 806 |
| 239 | red | 745 | 330 | **746** | 624 | 746 |
| 101 | amber | 709 | 662 | **714** | 778 | 712 |
| 171 | not_assessed | 67 | 671 | **724** | 620 | 645 |
| 142 | red | 593 | 514 | **680** | 683 | 626 |
| 152 | red | 581 | 372 | **643** | 642 | 624 |
| 71 | amber | 8 | 539 | **621** | 391 | 574 |
| 8 | red | 11 | 513 | **550** | 419 | 483 |
| 85 | red | 480 | 283 | **738** | 724 | 668 |
| 81 | red | 450 | 266 | **443** | 435 | 385 |
| 228 | amber | 448 | 367 | **485** | 474 | 482 |
| 90 | red | 434 | 258 | **554** | 425 | 523 |
| 308 | red | 430 | 291 | **423** | 420 | 421 |
| 11 | amber | 388 | 333 | **431** | 422 | 428 |
| 265 | red | 380 | 268 | **387** | 389 | 387 |
- Across 155 assessed neighbourhoods: civic/OSM median 1.11, civic/Microsoft median 1.20; civic between OSM and Microsoft in 45 of 155
