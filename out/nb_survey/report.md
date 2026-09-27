# New Brunswick survey: frozen scan on more communities

Parameters (frozen, identical everywhere): 50 m blockage radius, 50 m sampling, neighbourhoods of 30+ mapped buildings, footprints >= 40 m2, buildings attached to roads within 150 m, not assessed within 2 km of the study-box edge. Counts are the higher of the OSM and Microsoft estimates (never their sum).

| Area | Mapped bldgs OSM | Microsoft | MS/OSM | Nbhds (30+) | Assessed | Red | Amber | Green | Not assessed | NA share | Box km2 | Assessable km2 | Runtime s | Peak MB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fredericton | 29,088 | 32,926 | 1.13 | 165 | 155 | 63 | 92 | 0 | 10 | 6% | 1761.4 | 1441.6 | 17 | 311 |
| pointe_sapin | 147 | 1,540 | 10.48 | 2 | 0 | 0 | 0 | 0 | 2 | 100% | 881.3 | 653.9 | 0 | 168 |
| moncton | 39,270 | 37,952 | 0.97 | 133 | 123 | 33 | 90 | 0 | 10 | 8% | 400.1 | 256.1 | 22 | 327 |
| saint_john | 22,203 | 19,738 | 0.89 | 101 | 79 | 37 | 42 | 0 | 22 | 22% | 324.0 | 196.0 | 17 | 251 |
| quispamsis | 1,364 | 8,894 | 6.52 | 39 | 24 | 12 | 12 | 0 | 15 | 38% | 100.0 | 36.0 | 4 | 199 |
| miramichi | 8,359 | 6,812 | 0.81 | 44 | 31 | 12 | 19 | 0 | 13 | 30% | 196.1 | 100.1 | 5 | 200 |
| bathurst | 3,994 | 5,647 | 1.41 | 39 | 26 | 8 | 18 | 0 | 13 | 33% | 144.1 | 64.1 | 2 | 186 |
| edmundston | 5,875 | 5,409 | 0.92 | 26 | 17 | 5 | 12 | 0 | 9 | 35% | 144.1 | 64.1 | 3 | 188 |
| campbellton | 1,733 | 3,092 | 1.78 | 13 | 11 | 3 | 8 | 0 | 2 | 15% | 100.1 | 36.1 | 2 | 177 |
| woodstock | 357 | 707 | 1.98 | 4 | 2 | 0 | 2 | 0 | 2 | 50% | 100.0 | 36.0 | 1 | 178 |
| grand_falls | 465 | 3,641 | 7.83 | 17 | 12 | 3 | 9 | 0 | 5 | 29% | 100.1 | 36.0 | 1 | 179 |
| sussex | 1,878 | 3,476 | 1.85 | 22 | 16 | 6 | 10 | 0 | 6 | 27% | 100.0 | 36.0 | 1 | 179 |
| shediac | 4,379 | 3,716 | 0.85 | 20 | 12 | 5 | 7 | 0 | 8 | 40% | 100.1 | 36.0 | 2 | 186 |
| sackville | 3,010 | 2,668 | 0.89 | 14 | 12 | 7 | 5 | 0 | 2 | 14% | 100.1 | 36.0 | 1 | 175 |
| st_stephen | 3,352 | 3,274 | 0.98 | 17 | 15 | 7 | 8 | 0 | 2 | 12% | 100.0 | 36.0 | 2 | 180 |
| caraquet | 229 | 2,284 | 9.97 | 10 | 7 | 1 | 6 | 0 | 3 | 30% | 100.1 | 36.1 | 1 | 172 |
| richibucto | 261 | 1,886 | 7.23 | 9 | 1 | 0 | 1 | 0 | 8 | 89% | 100.1 | 36.0 | 0 | 170 |
| **Total (17 areas)** | **125,964** | **143,662** | 1.14 | **675** | **543** | **202** | **341** | **0** | **132** | 20% | | | | |

## Top 10 neighbourhoods province-wide (mapped buildings cut off by the worst sampled blockage)

| # | Area | nid | Status | Cut off (headline) | Cut off OSM / MS | Mapped bldgs OSM / MS | Connections | Choke (lon, lat) |
|---:|---|---:|---|---:|---|---|---:|---|
| 1 | saint_john | 189 | red | 802 | 802 / 684 | 802 / 684 | 1 | [-66.105028, 45.257646] |
| 2 | fredericton | 308 | red | 430 | 430 / 291 | 430 / 291 | 2 | [-66.559566, 45.894666] |
| 3 | fredericton | 90 | red | 416 | 416 / 249 | 434 / 258 | 2 | [-66.742532, 45.981465] |
| 4 | fredericton | 8 | red | 363 | 0 / 363 | 11 / 513 | 2 | [-66.701491, 45.867809] |
| 5 | saint_john | 41 | red | 330 | 330 / 222 | 330 / 222 | 1 | [-66.093216, 45.246626] |
| 6 | saint_john | 159 | red | 307 | 307 / 288 | 307 / 288 | 1 | [-66.113436, 45.293215] |
| 7 | saint_john | 121 | red | 295 | 295 / 266 | 296 / 267 | 1 | [-66.002892, 45.247443] |
| 8 | saint_john | 127 | red | 285 | 285 / 192 | 286 / 193 | 1 | [-66.02808, 45.307067] |
| 9 | moncton | 182 | red | 243 | 243 / 99 | 243 / 99 | 2 | [-64.785326, 46.040239] |
| 10 | moncton | 224 | red | 215 | 213 / 215 | 213 / 215 | 1 | [-64.832953, 46.12999] |

## Source disagreement (OSM vs Microsoft)

| Area | Box MS/OSM | Assessed nbhds with one source > 3x the other | Median nbhd MS/OSM (assessed) |
|---|---:|---:|---:|
| fredericton | 1.13 | 40 of 155 | 0.90 |
| pointe_sapin | 10.48 **(>3x)** | 0 of 0 | nan |
| moncton | 0.97 | 6 of 123 | 0.97 |
| saint_john | 0.89 | 1 of 79 | 0.90 |
| quispamsis | 6.52 **(>3x)** | 18 of 24 | 21.99 |
| miramichi | 0.81 | 0 of 31 | 0.79 |
| bathurst | 1.41 | 9 of 26 | 0.90 |
| edmundston | 0.92 | 1 of 17 | 0.81 |
| campbellton | 1.78 | 2 of 11 | 1.56 |
| woodstock | 1.98 | 0 of 2 | 1.59 |
| grand_falls | 7.83 **(>3x)** | 9 of 12 | 37.17 |
| sussex | 1.85 | 5 of 16 | 0.93 |
| shediac | 0.85 | 4 of 12 | 0.47 |
| sackville | 0.89 | 0 of 12 | 0.85 |
| st_stephen | 0.98 | 1 of 15 | 0.75 |
| caraquet | 9.97 **(>3x)** | 7 of 7 | 16.33 |
| richibucto | 7.23 **(>3x)** | 1 of 1 | 10.67 |
