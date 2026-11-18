# Station access review: first Footscray-to-Flinders Street pilot

## Decision and scope

The [completed boundary diagnostic](commute_walk_boundary_review.md#completed-real-data-boundary-checkpoint) explains concrete exclusions at Footscray and Dandenong. The next implementation target is one documented origin-destination pair: a reviewed public location at Footscray and one at Flinders Street. The other three origin candidates remain in the project for later expansion. No location is approved by this document, and `config/routing_pilot.json` remains at input preflight with null street-network and location fields.

This step establishes the identity and geometry of the two proposed access points. It does not infer a public entrance from a GTFS parent station, a turnstile label, or the size of an OSM component.

## Operator evidence reviewed on 18 November 2026

[Metro's official virtual-tour index](https://www.metrotrains.com.au/station-accessibility-features/virtual-station-tours/) links the two supporting documents below. Their filenames identify January 2021 updates and their URLs use a June 2021 upload directory. They describe station layout but do not by themselves establish operating conditions on 13 October 2026.

| Station | Official source | Relevant evidence and limitation |
| --- | --- | --- |
| Footscray | [Metro supporting document](https://ds12k1658w1f2.cloudfront.net/wp-content/uploads/2021/06/Footscray-Station-virtual-tour-DAT-TOC-update-January-21.docx.pdf), physical pages 4-6 | Describes the Irving/Hyde Street footbridge and access involving McNab Avenue. The McNab forecourt has level access to platforms 4 and 5 and links to the footbridge through vertical access features. It does not identify our OSM node or bridge way. |
| Flinders Street | [Metro supporting document](https://ds12k1658w1f2.cloudfront.net/wp-content/uploads/2021/06/Flinders-St.-Station-DAT-TOC-version-update-Jan-21.docx.pdf), physical pages 3-4 | Identifies the main entrance beneath the clocks at the southwest Flinders/Swanston corner as stair access and distinguishes level-access entrances on Swanston Street. This supports a specific entrance-identity comparison, not an approved OSM-coordinate match. |
| Flinders Street layout | [PTV precinct map](https://www.ptv.vic.gov.au/assets/DTP1124-FlindersStreetStation-Precinct-Map_Degraves-Subway_web_Stage-1_v3.pdf), one page | Shows named street/river exits and access features. It also labels Campbell Arcade closed for construction. Its effective date for the pilot has not been established, so that closure label is not adopted as an October 2026 fact. |

Both Metro documents explicitly warn that works can make their descriptions outdated. Their old opening hours and service details are not imported into the pilot.

## Match to the dated OSM geometry

The current Footscray candidate is node `3953464544` on way `241661387`. The real boundary report additionally identifies bridge footway `1499210381`, McNab Avenue way `28615601`, and steps `51335781`. The operator description gives a named layout against which these objects can be checked; the bridge's station identity is not inferred from `bridge=yes` alone.

For Flinders Street, earlier manual OPL evidence recorded candidate node `13293687371` on stair way `46325052`, tagged with nine steps and no ramp, and on corridor `185737824`. Nearby corridor `1420649145` includes another candidate, `13316343402`. Comparing their exact geometry with the named corner entrance is a review hypothesis. The tag `railway=subway_entrance` alone does not distinguish station identity, nor does it establish step-free access.

Obtain one compact text extract from the original dated Victoria snapshot. Run this from Anaconda Prompt / CMD with `homereach-osm` active:

```bat
cd /d "D:\My project\homereach_melbourne"
conda activate homereach-osm
osmium getid -r "data\raw\routing\victoria-261001.osm.pbf" n3953464544 n13293687371 w241661387 w1499210381 w28615601 w51335781 w46325052 w185737824 w1420649145 -f opl -o "data\interim\routing\footscray_flinders_access_review.opl.txt"
```

The command writes a small derived text file containing the selected objects and referenced nodes, including coordinates and available tags. It leaves the original PBF unchanged. No overwrite flag is used. The original source SHA-256 previously recorded is `5e775844a1b4424dc3c549e601c4a014f4d2816fe7f0ea3fda7d1b39fb966cc0`.

The extract is supporting geometry, not a complete station network or routing input. Review the candidate points against the operator layout; distinguish the public side of the entrance from paid barriers, platforms, bridge decks and stair endpoints. Record any unmatched identity, level or access rule. A successful extraction is not approval of the candidates.

The [Osmium getid manual](https://docs.osmcode.org/osmium/latest/osmium-getid.html) documents ID selection and recursive inclusion of referenced objects. OSM data remains © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), under the [Open Database License](https://opendatacommons.org/licenses/odbl/1-0/).

## Following implementation step

Once the geometry is available, record one defensible origin and destination with source IDs, coordinates, CRS, entrance identity, evidence dates and remaining uncertainty. Validate the separate routing runtime with a tiny synthetic fixture and record the actual Python, Java and engine versions before attempting the first Melbourne itinerary. Use the audited timetable and a separately reviewed complete street-network source, not the filtered highway diagnostic file.

The first itinerary is a bounded development check. Review its walking access, platform connection, transfers and timing before expanding to the other three origins or integrating anything into the explorer. The fixed October 2026 timetable, earlier OSM snapshot and 2025Q3 rental data retain their separate dates.
