"""Content of the /off-the-clock page: trips, newest first, with their photos.

Photos live in app/static/img/offclock/ as <name>-s.webp (long edge 900 px) and <name>-l.webp (2000 px).
`size` is the pixel size of the large copy; the small one has the same proportions.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Photo:
    name: str
    size: tuple[int, int]
    alt: str
    caption: str

    @property
    def portrait(self) -> bool:
        return self.size[1] > self.size[0]

    @property
    def small_width(self) -> int:
        return round(900 * self.size[0] / max(self.size))


@dataclass(frozen=True)
class Trip:
    slug: str
    when: str            # shown in the trip log, e.g. "08.2026"
    place: str
    country: str
    activity: str
    story: str
    photos: tuple[Photo, ...] = field(default_factory=tuple)
    # pair | trio | solo (portrait beside the text) | aside (landscape beside the text) | with-map
    # | mosaic (three landscapes: one large, two stacked beside it)
    layout: str = "pair"
    rows: tuple[int, ...] = ()  # photos per row; empty means all of them in one row

    @property
    def photo_rows(self) -> tuple[tuple[Photo, ...], ...]:
        out, at = [], 0
        for n in self.rows or (len(self.photos),):
            out.append(self.photos[at:at + n])
            at += n
        return tuple(out)


TRIPS: tuple[Trip, ...] = (
    Trip("georgia", "08.2026", "Across the Caucasus", "Georgia", "Hiking",
         "A summer in the Caucasus instead of the Alps: Mestia in Svaneti, Omalo in Tusheti, and Kazbek showing up "
         "between the clouds. Long walks up the valleys until a glacier filled the whole frame.",
         (Photo("georgia-1", (1941, 2000), "Paweł on a green valley trail below a rocky, glaciated peak in the Caucasus",
                "Svaneti. The trail follows the river up to the ice."),
          Photo("georgia-3", (2000, 1126), "Grey rock towers above green summer pastures under white clouds",
                "Rock towers over the summer pastures."),
          Photo("georgia-2", (1333, 2000), "A glacier ending in a rock wall with a waterfall, forest below",
                "Where the glacier ends: meltwater over the rock band."),
          Photo("georgia-4", (2000, 1333), "The snowy summit of Kazbek between clouds, above a dark moraine",
                "Kazbek, for the minute the cloud allowed."),
          Photo("georgia-5", (1333, 2000), "A white horse among thistles on a pasture in warm evening light",
                "Evening on the pasture. He came over to check the camera.")),
         "pair", (2, 3)),
    Trip("austria-2026", "05.2026", "By bike to the snow", "Hintertux, Zillertal, Austria", "Bike + ski touring",
         "By May the snow in the Zillertal has retreated to the head of the valley, up at Hintertux. So the skis go "
         "on the backpack, the bike does the valley road, and the skiing starts where the tarmac ends.",
         (Photo("austria-bike-1", (1333, 2000), "Paweł on a bike on a mountain road with skis strapped to his backpack",
                "The approach. Skis on the pack, shorts on the rider."),),
         "solo"),
    Trip("switzerland", "02.2026", "Swiss Alps", "Switzerland", "Downhill & ski touring",
         "A February trip to Switzerland: wide groomed slopes in the morning, and a pair of touring skis for "
         "everything the lifts don't reach.",
         (Photo("switzerland-1", (2000, 1333), "A snowy ridge in sunlight with dark valleys and heavy cloud behind",
                "Light on the ridge, weather in the valley."),
          Photo("switzerland-3", (2000, 1334), "Sunlit snow slopes with ski tracks below a rocky top and a deep blue sky",
                "Somebody got there first."),
          Photo("switzerland-2", (2000, 1333), "Paweł standing in the snow holding a yellow ski upright, mountains behind",
                "The yellow skis have seen most of this page.")),
         "mosaic"),
    Trip("bieszczady", "01.2026", "Połonina Caryńska", "Bieszczady, Poland", "Ski touring",
         "The one I keep coming back to. Every winter I go to the Bieszczady for ski touring and by now I've done "
         "all the routes. No lifts, no queues, just the long bare ridges of the połoniny.",
         (Photo("bieszczady-1", (2000, 1333), "Paweł on touring skis on a snowy ridge, forested hills to the horizon",
                "Połonina Caryńska in January."),
          Photo("bieszczady-2", (2000, 1333), "A sea of cloud filling the valleys, one wooded ridge rising out of it",
                "Above the cloud. The valleys stayed grey all day.")),
         "pair"),
    Trip("dolomites", "08–09.2025", "Tre Cime & via ferratas", "Dolomites, Italy", "Via ferrata",
         "A week of steel cables and limestone. Clipped in on the via ferratas, then a walk around the Tre Cime "
         "while the cloud sat on the summits.",
         (Photo("dolomites-1", (2000, 1333), "The three towers of Tre Cime di Lavaredo under heavy cloud",
                "Tre Cime di Lavaredo."),
          Photo("dolomites-2", (1333, 2000), "Carabiners clipped to a via ferrata cable with Dolomite towers behind",
                "Two carabiners, one cable, a lot of air.")),
         "pair"),
    Trip("istria", "08.2025", "Around Istria", "Italy · Slovenia · Croatia", "Cycling",
         "The whole peninsula in four days, Trieste to Trieste. Down the west coast, around the southern tip and "
         "back up the other side, with the Adriatic on one shoulder nearly all the way.",
         (Photo("istria-1", (2000, 1568), "Paweł in a cycling jersey holding a helmet at sunset, sea and hills behind",
                "Evening light, day's riding done."),),
         "with-map"),
    Trip("austria", "04.2025", "Penken", "Zillertal, Austria", "Skiing",
         "Late April on the Penken. The season was ending: more rock than snow on the ridge, and the big white "
         "peaks only in the distance.",
         (Photo("austria-1", (2000, 1333), "A rocky ridge with patches of snow and a snowy mountain range under clouds",
                "End of the season above the Zillertal."),),
         "aside"),
    Trip("france", "02.2025", "Les 3 Vallées", "French Alps", "Downhill",
         "A week of downhill in the Three Valleys, one of the largest linked ski areas there is. Long days, black "
         "runs, and one local who watched it all from the trees.",
         (Photo("france-1", (2000, 1436), "Ski slopes and a snowy peak, with a black piste marker reading Lac Noir 7",
                "Lac Noir, marker 7."),
          Photo("france-2", (1333, 2000), "Snowy peaks and pistes under a cloudless dark blue sky",
                "Not a cloud for days."),
          Photo("france-3", (1647, 2000), "A brown and white dog sitting in deep snow among bare branches",
                "Not everyone was there for the skiing.")),
         "trio"),
    Trip("norway", "03.2023", "Tromsø", "Northern Norway", "Ski touring",
         "North of the Arctic Circle in March, where the snow runs all the way down to the fjord.",
         (Photo("norway-1", (2000, 901), "A fjord seen through bare birches, with snowy mountains on the far shore",
                "Tromsø. Taken on a phone, before the Fuji."),),
         "aside"),
    Trip("slovenia", "09.2022", "Triglav", "Julian Alps, Slovenia", "Via ferrata",
         "Triglav, the highest peak in Slovenia. Helmet, harness, a steel cable and a long way down to the valley.",
         (Photo("slovenia-1", (2000, 900), "A climber in a helmet on a via ferrata, with a deep valley and peaks behind",
                "On the cable in the Julian Alps."),),
         "aside"),
)

# Shown on the home page as a teaser for the full page.
TEASER: tuple[Photo, ...] = (TRIPS[3].photos[0], TRIPS[4].photos[0], TRIPS[0].photos[3])
