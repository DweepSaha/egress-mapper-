# Method-assumption check (diagnostic only)

Read-only analysis of the OSM data on disk. Nothing in the app, scan or mitigation logic was changed.

**Upstream filter (important context):** the road graphs were built from ways matching OSMnx 2.1.1's `network_type="drive"` filter, which already EXCLUDES `access=private`, `motor_vehicle=no`, `motorcar=no`, `highway=track|service|...` and `service=emergency_access|driveway|parking|private`. Such roads are not in the network at all, so they cannot be counted as ways out. The checks below look for restrictions that pass that filter.

Exact queries:
- Access restriction (way tag): access ∈ ['customers', 'destination', 'no', 'permit', 'private'], or motor_vehicle ∈ ['no', 'private']
- Barrier (node tag, node is part of the way and lies on the engine road segment, ≤ 2 m): barrier ∈ ['block', 'bollard', 'gate', 'lift_gate']
- Surface: surface ∈ ['dirt', 'gravel', 'ground', 'unpaved'] (reported separately: other unpaved values ['compacted', 'earth', 'fine_gravel', 'grass', 'mud', 'pebblestone', 'rock', 'sand'])
- smoothness ∈ ['bad', 'horrible', 'impassable', 'very_bad', 'very_horrible']; tracktype ∈ ['grade3', 'grade4', 'grade5']; seasonal=yes; highway=track
- One-way: oneway ∈ ['-1', '1', 'reversible', 'true', 'yes'] on any OSM way making up the segment
- Vulnerable occupancy: amenity ∈ ['clinic', 'hospital', 'kindergarten', 'nursing_home', 'school', 'social_facility'] (nodes and polygons), attached to the nearest road segment
  within 150 m (the same rule used for mapped buildings)
- "Qualifying road segment": an engine road segment whose highway class is in the qualifying classes
  ['motorway', 'motorway_link', 'primary', 'primary_link', 'secondary', 'secondary_link', 'tertiary', 'tertiary_link', 'trunk', 'trunk_link'] (before the spur rule). "Way out": a qualifying segment the engine keeps as a way out
  after the spur rule (Edge.exit). "Used as a way out by a scanned neighbourhood": a way-out segment that meets one of
  the connection points (gateways) of a neighbourhood in the scan results (30+ mapped buildings).

## Fredericton, NB

Road segments: 6608 (qualifying 2430, of which kept as ways out 2321). Scanned neighbourhoods: 165. OSM ways not found in the extract: 0.
### 1. Access restrictions / barriers on qualifying roads
- Qualifying segments with any restriction or barrier: **41** of 2430
- Tag counts: {'access=no': 4, 'access=permit': 34, 'barrier=gate': 5, 'barrier=lift_gate': 1}
  - primary 'Chemin Lincoln Road' (619 m): access=no (way/396583278); way out: yes
  - primary 'Chemin Lincoln Road' (835 m): access=no (way/396583278); way out: yes
  - tertiary 'Tilley Avenue' (557 m): access=permit (way/734160936); way out: yes
  - tertiary 'Ganong Street' (199 m): access=permit (way/733959253); way out: no (spur rule)
  - tertiary 'Ganong Street' (243 m): access=permit (way/733959253); way out: no (spur rule)
  - tertiary 'Ganong Street' (286 m): access=permit (way/733959253); way out: no (spur rule)
  - tertiary 'Champlain Avenue' (244 m): access=permit (way/108650584); way out: yes; meets the connection point of scanned neighbourhood(s) nid 190 (not_assessed, 81 mapped buildings)
  - tertiary 'Ganong Street' (391 m): access=permit (way/733959253); way out: yes; meets the connection point of scanned neighbourhood(s) nid 190 (not_assessed, 81 mapped buildings)
  - tertiary 'Ganong Street' (232 m): access=permit (way/733959253), barrier=gate (node/1246481767); way out: no (spur rule)
  - tertiary 'Ganong Street' (428 m): access=permit (way/733959253); way out: yes; meets the connection point of scanned neighbourhood(s) nid 403 (red, 90 mapped buildings)
  - tertiary 'Ganong Street' (548 m): access=permit (way/733959253); way out: yes; meets the connection point of scanned neighbourhood(s) nid 403 (red, 90 mapped buildings)
  - tertiary 'Ganong Street' (267 m): access=permit (way/733959253); way out: yes
  - tertiary 'Ganong Street' (331 m): access=permit (way/733959253); way out: yes
  - tertiary 'Champlain Avenue' (569 m): access=permit (way/108650584); way out: yes
  - tertiary 'Champlain Avenue' (222 m): access=permit (way/108650584); way out: yes
  - tertiary 'Champlain Avenue' (326 m): access=permit (way/108650584); way out: yes
  - tertiary 'Champlain Avenue' (352 m): access=permit (way/108650584); way out: yes
  - tertiary 'Champlain Avenue' (35 m): access=permit (way/108650584); way out: yes
  - tertiary_link '(unnamed)' (56 m): access=permit (way/734160937); way out: yes
  - tertiary_link '(unnamed)' (59 m): access=permit (way/734160938); way out: yes
  - tertiary 'Ganong Street' (626 m): access=permit (way/733959253), barrier=lift_gate (node/1246482375); way out: yes
  - tertiary 'Tilley Avenue' (112 m): access=permit (way/734160936); way out: yes
  - tertiary 'Tilley Avenue' (229 m): access=permit (way/734160936); way out: yes
  - tertiary 'Tilley Avenue' (80 m): access=permit (way/734160936); way out: yes
  - tertiary 'Tilley Avenue' (296 m): access=permit (way/734160936); way out: yes
  - tertiary 'Champlain Avenue' (54 m): access=permit (way/108650584); way out: yes
  - tertiary 'Champlain Avenue' (122 m): access=permit (way/108650584); way out: yes
  - tertiary 'Champlain Avenue' (116 m): access=permit (way/108650584); way out: yes
  - tertiary 'Champlain Avenue' (25 m): access=permit (way/108650584); way out: yes
  - tertiary 'Tilley Avenue' (112 m): access=permit (way/734160936); way out: yes
  - tertiary 'Tilley Avenue' (244 m): access=permit (way/734160936); way out: yes
  - tertiary 'Champlain Avenue' (158 m): access=permit (way/108650584); way out: yes
  - tertiary 'Tilley Avenue' (36 m): access=permit (way/734160936); way out: yes
  - tertiary 'Champlain Avenue' (59 m): access=permit (way/108650584); way out: yes; meets the connection point of scanned neighbourhood(s) nid 190 (not_assessed, 81 mapped buildings)
  - tertiary 'Champlain Avenue' (588 m): access=permit (way/108650584); way out: yes; meets the connection point of scanned neighbourhood(s) nid 190 (not_assessed, 81 mapped buildings)
  - tertiary 'Tilley Avenue' (37 m): access=permit (way/734160936); way out: yes
  - tertiary '(unnamed)' (42 m): barrier=gate (node/1194656503); way out: no (spur rule)
  - tertiary '(unnamed)' (15 m): barrier=gate (node/1194756388); way out: no (spur rule)
  - tertiary 'Chapel Road' (35 m): barrier=gate (node/1196368793); way out: no (spur rule)
  - tertiary '(unnamed)' (653 m): barrier=gate (node/1196368793); way out: no (spur rule)
  - secondary_link '(unnamed)' (53 m): access=no (way/498295910), access=no (way/498296068); way out: yes
- **Restricted qualifying segments used as a way out at a scanned neighbourhood's connection point: 6**
  - nid 190 (not_assessed, 81 mapped buildings, worst sampled blockage 0): 2 of its 5 connection point(s) sit on a restricted road; centre ≈ 45.80457, -66.42847
  - nid 403 (red, 90 mapped buildings, worst sampled blockage 90): 1 of its 1 connection point(s) sit on a restricted road; centre ≈ 45.85243, -66.43723
- Restricted segments kept as ways out anywhere in the network (not necessarily at a connection point): 33
- (Context) Local roads inside scanned neighbourhoods with a restriction/barrier: 80 - nid 1: barrier=gate (node/1710164059); nid 9: barrier=gate (node/1197556125); nid 69: barrier=gate (node/578207138); nid 171: barrier=gate (node/1202535962); nid 190: barrier=gate (node/1246301182); nid 190: access=permit (way/108711719), barrier=gate (node/1246485426); nid 190: access=permit (way/108711570); nid 190: access=permit (way/500419984) …
- Not tagged: 2387 of 2430 qualifying segments have no access tag at all (absence ≠ confirmed public).

### 2. Surface and seasonal quality (qualifying roads only)
- Qualifying segments with any flag: **28** of 2430; tag counts: {'surface=unpaved': 28}
- **Flagged qualifying segments used as a way out at a scanned neighbourhood's connection point: 0**
- Not tagged: 1286 of 2430 qualifying segments have no surface tag; smoothness/tracktype/seasonal are rarely tagged at all. highway=track is excluded upstream by the OSMnx 'drive' filter, so it is 0 by construction.

### 3. One-way coverage (all road segments)
- oneway on 1043 of 6608 segments (15.8%), 262.5 of 2006.2 km (13.1% of length); on qualifying roads: 836 of 2430 segments. Mostly divided carriageways / ramps expected; the analysis treats every road as two-way.

### 4. Vulnerable occupancies in RED neighbourhoods (display-only finding)
- Amenity features found: 86; attached to a road within 150 m: 77; in RED neighbourhoods: **8**
  - nid 81 (RED, 450 mapped buildings, worst sampled blockage cuts off 151): clinic '(unnamed)' [node/14098080564], 41 m from its road; not on a stranded street under the worst sampled blockage
  - nid 81 (RED, 450 mapped buildings, worst sampled blockage cuts off 151): clinic 'Veteran's Memorial Health Centre' [way/105671778], 37 m from its road; not on a stranded street under the worst sampled blockage
  - nid 81 (RED, 450 mapped buildings, worst sampled blockage cuts off 151): hospital '(unnamed)' [way/575567743], 31 m from its road; not on a stranded street under the worst sampled blockage
  - nid 81 (RED, 450 mapped buildings, worst sampled blockage cuts off 151): school 'Chief Harold Sappier Memorial Elementary School' [way/575567738], 74 m from its road; not on a stranded street under the worst sampled blockage
  - nid 85 (RED, 480 mapped buildings, worst sampled blockage cuts off 53): social_facility (assisted_living) 'Windsor Court' [way/105679065], 41 m from its road; not on a stranded street under the worst sampled blockage
  - nid 90 (RED, 434 mapped buildings, worst sampled blockage cuts off 416): school 'Douglas Elementary School' [node/412195367], 22 m from its road; not on a stranded street under the worst sampled blockage
  - nid 141 (RED, 294 mapped buildings, worst sampled blockage cuts off 114): social_facility (group_home) 'Shannex Parkland' [way/398437086], 118 m from its road; not on a stranded street under the worst sampled blockage
  - nid 400 (RED, 35 mapped buildings, worst sampled blockage cuts off 34): school 'Welamukotuk Kinapuwi Kehkitimok' [way/1502354348], 31 m from its road; on a street stranded by the worst sampled blockage

## Upper Tantallon, NS

Road segments: 2455 (qualifying 725, of which kept as ways out 610). Scanned neighbourhoods: 86. OSM ways not found in the extract: 0.
### 1. Access restrictions / barriers on qualifying roads
- Qualifying segments with any restriction or barrier: **3** of 725
- Tag counts: {'barrier=gate': 1, 'access=no': 2}
  - unclassified 'Pockwock Road' (1444 m): barrier=gate (node/1369502638); way out: no (spur rule)
  - motorway_link '(unnamed)' (193 m): access=no (way/122666617); way out: yes
  - motorway_link '(unnamed)' (313 m): access=no (way/122666619); way out: yes
- **Restricted qualifying segments used as a way out at a scanned neighbourhood's connection point: 0**
- Restricted segments kept as ways out anywhere in the network (not necessarily at a connection point): 2
- (Context) Local roads inside scanned neighbourhoods with a restriction/barrier: 10 - nid 96: access=destination (way/70639335); nid 96: access=destination (way/70639325); nid 96: access=destination (way/70639344); nid 96: barrier=block (node/11047292320); nid 191: access=destination (way/436730428); nid 191: access=destination (way/480537975); nid 191: access=destination (way/537296918); nid 191: access=destination (way/1056332268) …
- Not tagged: 717 of 725 qualifying segments have no access tag at all (absence ≠ confirmed public).

### 2. Surface and seasonal quality (qualifying roads only)
- Qualifying segments with any flag: **2** of 725; tag counts: {'surface=unpaved': 1, 'surface=gravel': 1}
- **Flagged qualifying segments used as a way out at a scanned neighbourhood's connection point: 0**
- Not tagged: 8 of 725 qualifying segments have no surface tag; smoothness/tracktype/seasonal are rarely tagged at all. highway=track is excluded upstream by the OSMnx 'drive' filter, so it is 0 by construction.

### 3. One-way coverage (all road segments)
- oneway on 283 of 2455 segments (11.5%), 104.1 of 727.5 km (14.3% of length); on qualifying roads: 233 of 725 segments. Mostly divided carriageways / ramps expected; the analysis treats every road as two-way.

### 4. Vulnerable occupancies in RED neighbourhoods (display-only finding)
- Amenity features found: 30; attached to a road within 150 m: 28; in RED neighbourhoods: **7**
  - nid 19 (RED, 68 mapped buildings, worst sampled blockage cuts off 33): school 'Sackville Heights Elementary School Park' [way/699660463], 93 m from its road; not on a stranded street under the worst sampled blockage
  - nid 58 (RED, 860 mapped buildings, worst sampled blockage cuts off 79): social_facility (group_home) 'Eleanor Hubley Villa' [way/358581245], 50 m from its road; not on a stranded street under the worst sampled blockage
  - nid 96 (RED, 177 mapped buildings, worst sampled blockage cuts off 177): school '(unnamed)' [relation/17834060], 105 m from its road; not on a stranded street under the worst sampled blockage
  - nid 117 (RED, 1666 mapped buildings, worst sampled blockage cuts off 213): school 'Madeline Symonds Middle School Park' [way/699305399], 35 m from its road; not on a stranded street under the worst sampled blockage
  - nid 117 (RED, 1666 mapped buildings, worst sampled blockage cuts off 213): social_facility (nursing_home) 'Whitehills' [way/567875489], 82 m from its road; not on a stranded street under the worst sampled blockage
  - nid 121 (RED, 1219 mapped buildings, worst sampled blockage cuts off 178): school 'Kingswood Elementary School Park' [way/1028834630], 120 m from its road; not on a stranded street under the worst sampled blockage
  - nid 168 (RED, 108 mapped buildings, worst sampled blockage cuts off 108): social_facility (group_home) 'Woodlyn Manor' [way/460641851], 45 m from its road; on a street stranded by the worst sampled blockage

## Pointe-Sapin, NB

Road segments: 191 (qualifying 98, of which kept as ways out 92). Scanned neighbourhoods: 2. OSM ways not found in the extract: 0.
### 1. Access restrictions / barriers on qualifying roads
- Qualifying segments with any restriction or barrier: **5** of 98
- Tag counts: {'barrier=gate': 5}
  - tertiary 'Chemin Cap-Saint-Louis' (4879 m): barrier=gate (node/1726020042); way out: no (spur rule)
  - tertiary 'Chemin Cap-Saint-Louis' (39 m): barrier=gate (node/1726020197); way out: no (spur rule)
  - primary 'Route 117' (1461 m): barrier=gate (node/1726868130); way out: yes
  - primary 'Route 117' (2245 m): barrier=gate (node/1726977041); way out: yes
  - primary 'Route 117' (1095 m): barrier=gate (node/1726977041); way out: yes
- **Restricted qualifying segments used as a way out at a scanned neighbourhood's connection point: 0**
- Restricted segments kept as ways out anywhere in the network (not necessarily at a connection point): 3
- (Context) Local roads inside scanned neighbourhoods with a restriction/barrier: 0
- Not tagged: 98 of 98 qualifying segments have no access tag at all (absence ≠ confirmed public).

### 2. Surface and seasonal quality (qualifying roads only)
- Qualifying segments with any flag: **2** of 98; tag counts: {'surface=compacted': 1, 'surface=unpaved': 1}
- **Flagged qualifying segments used as a way out at a scanned neighbourhood's connection point: 0**
- Not tagged: 2 of 98 qualifying segments have no surface tag; smoothness/tracktype/seasonal are rarely tagged at all. highway=track is excluded upstream by the OSMnx 'drive' filter, so it is 0 by construction.

### 3. One-way coverage (all road segments)
- oneway on 6 of 191 segments (3.1%), 2.8 of 218.2 km (1.3% of length); on qualifying roads: 6 of 98 segments. Mostly divided carriageways / ramps expected; the analysis treats every road as two-way.

### 4. Vulnerable occupancies in RED neighbourhoods (display-only finding)
- Amenity features found: 2; attached to a road within 150 m: 2; in RED neighbourhoods: **0**

## Summary
- Fredericton, NB: restricted qualifying segments 41 (used as a way out at a scanned neighbourhood's connection point: 6); surface/seasonal-flagged 28 (used: 0); vulnerable occupancies in RED neighbourhoods 8
- Upper Tantallon, NS: restricted qualifying segments 3 (used as a way out at a scanned neighbourhood's connection point: 0); surface/seasonal-flagged 2 (used: 0); vulnerable occupancies in RED neighbourhoods 7
- Pointe-Sapin, NB: restricted qualifying segments 5 (used as a way out at a scanned neighbourhood's connection point: 0); surface/seasonal-flagged 2 (used: 0); vulnerable occupancies in RED neighbourhoods 0
