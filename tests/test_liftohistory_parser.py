"""Locks in parse_liftohistory() — the pure text -> Workout parser that
sources/api.py feeds real Liftosaur REST API responses through. A pure
function with real fixtures below (fetched via the MCP `get_history` tool
on 2026-09-13) plus the reference doc's synthetic edge cases, so every
case here is exercised with no mocking or I/O.
"""

from liftostrava.models import Exercise, Set, Workout
from liftostrava.sources.liftohistory import parse_liftohistory

# Real record: kg-only weights, an exercise with only completed sets and
# no warmup/target at all ("Incline Crunch"), unilateral sets that happen
# to be symmetric ("3x11|11").
REAL_RECORD_WITH_BARE_EXERCISE = """\
2026-09-11 17:30:05 +00:00 / program: "L/S/U" / dayName: "Upper" / week: 1 / dayInWeek: 3 / duration: 2625s / exercises: {
  Bench Press / 2x8 42.5kg, 1x6 42.5kg / warmup: 1x5 20kg / target: 3x8 42.5kg 60s
  Shoulder Press, Leverage Machine / 1x3 20kg, 2x5 15kg / warmup: 1x5 10kg / target: 3x9 20kg 60s
  Bicep Curl / 3x11|11 10kg / target: 3x11 10kg 60s
  Incline Crunch / 3x12 0kg
}"""

# Real record: unilateral sets that are genuinely asymmetric
# ("1x10|10, 2x9|9") plus a mix of rep counts within one exercise.
REAL_RECORD_WITH_ASYMMETRIC_UNILATERAL = """\
2026-09-09 06:37:54 +00:00 / program: "L/S/U" / dayName: "Stability" / week: 1 / dayInWeek: 2 / duration: 2725s / exercises: {
  Single Leg Deadlift / 1x10|10 10kg, 2x9|9 10kg / target: 3x12 10kg 60s
  Leg Extension / 1x10 27.5kg, 2x12 27.5kg / warmup: 1x8 17.5kg / target: 3x10 27.5kg 90s
}"""

# From get_liftohistory_reference: lb units, AMRAP "+", RPE "@N", a
# workout note and an exercise note, an exercise with no warmup at all
# ("OHP"), and an equipment suffix kept whole ("Bench Press, Barbell").
REFERENCE_DOC_EXAMPLE = """\
// Optional workout note
2026-02-28T10:45:30Z / program: "5/3/1 For Beginners" / dayName: "Push Day" / week: 1 / dayInWeek: 5 / duration: 1235s / exercises: {
  // Optional exercise note
  Bench Press, Barbell / 3x8 185lb @7, 1x6 185lb @9 / warmup: 1x10 95lb, 1x5 135lb / target: 3x8-12 185lb @8 90s
  OHP / 3x10 95lb / target: 3x10 95lb 60s
  Pull Ups / 3x8|7 0lb / target: 3x10 0lb 60s
}"""


def test_parses_real_record_with_a_bare_no_warmup_no_target_exercise():
    workout = parse_liftohistory(REAL_RECORD_WITH_BARE_EXERCISE)

    assert workout == Workout(
        start_time="2026-09-11T17:30:05Z",
        elapsed_time=2625,
        name="L/S/U - Upper",
        description=None,
        utc_offset=None,
        exercises=[
            Exercise(
                name="Bench Press",
                sets=[
                    Set(8, 42.5, "kg"),
                    Set(8, 42.5, "kg"),
                    Set(6, 42.5, "kg"),
                ],
            ),
            Exercise(
                name="Shoulder Press, Leverage Machine",
                sets=[Set(3, 20, "kg"), Set(5, 15, "kg"), Set(5, 15, "kg")],
            ),
            Exercise(
                name="Bicep Curl",
                sets=[Set(11, 10, "kg"), Set(11, 10, "kg"), Set(11, 10, "kg")],
            ),
            Exercise(name="Incline Crunch", sets=[Set(12, 0, "kg")] * 3),
        ],
    )


def test_normalizes_the_space_plus_offset_date_form_to_utc_z():
    # "2026-09-11 17:30:05 +00:00" (real records) rather than
    # "2026-09-11T17:30:05Z" (reference doc / API docs example) — both
    # must produce the same normalized start_time.
    workout = parse_liftohistory(REAL_RECORD_WITH_BARE_EXERCISE)
    assert workout.start_time == "2026-09-11T17:30:05Z"


def test_unilateral_sets_take_only_the_first_number_symmetric():
    workout = parse_liftohistory(REAL_RECORD_WITH_BARE_EXERCISE)
    bicep_curl = next(e for e in workout.exercises if e.name == "Bicep Curl")
    assert bicep_curl.sets == [Set(11, 10, "kg")] * 3


def test_unilateral_sets_take_only_the_first_number_asymmetric():
    workout = parse_liftohistory(REAL_RECORD_WITH_ASYMMETRIC_UNILATERAL)
    deadlift = next(e for e in workout.exercises if e.name == "Single Leg Deadlift")
    # "1x10|10 10kg, 2x9|9 10kg" -> the "|N" side is dropped entirely.
    assert deadlift.sets == [Set(10, 10, "kg"), Set(9, 10, "kg"), Set(9, 10, "kg")]


def test_drops_warmup_and_target_sets_keeping_only_completed():
    workout = parse_liftohistory(REAL_RECORD_WITH_ASYMMETRIC_UNILATERAL)
    leg_extension = next(e for e in workout.exercises if e.name == "Leg Extension")
    # warmup: 1x8 17.5kg and target: 3x10 27.5kg are both absent.
    assert leg_extension.sets == [
        Set(10, 27.5, "kg"),
        Set(12, 27.5, "kg"),
        Set(12, 27.5, "kg"),
    ]


def test_parses_the_reference_docs_synthetic_example():
    workout = parse_liftohistory(REFERENCE_DOC_EXAMPLE)

    assert workout == Workout(
        start_time="2026-02-28T10:45:30Z",
        elapsed_time=1235,
        name="5/3/1 For Beginners - Push Day",
        description=None,
        utc_offset=None,
        exercises=[
            Exercise(
                name="Bench Press, Barbell",
                sets=[Set(8, 185, "lb")] * 3 + [Set(6, 185, "lb")],
            ),
            Exercise(name="OHP", sets=[Set(10, 95, "lb")] * 3),
            Exercise(name="Pull Ups", sets=[Set(8, 0, "lb")] * 3),
        ],
    )


def test_amrap_plus_marker_is_ignored():
    text = (
        "2026-01-15T10:00:00Z / duration: 60s / exercises: {\n"
        "  Deadlift / 1x5+ 185lb\n"
        "}"
    )
    workout = parse_liftohistory(text)
    assert workout.exercises == [Exercise(name="Deadlift", sets=[Set(5, 185, "lb")])]


def test_rpe_suffix_is_ignored():
    text = (
        "2026-01-15T10:00:00Z / duration: 60s / exercises: {\n  Squat / 3x8 185lb @7\n}"
    )
    workout = parse_liftohistory(text)
    assert workout.exercises == [Exercise(name="Squat", sets=[Set(8, 185, "lb")] * 3)]


def test_name_falls_back_to_program_only_when_dayname_missing():
    text = '2026-01-15T10:00:00Z / program: "5/3/1" / duration: 60s / exercises: {\n}'
    workout = parse_liftohistory(text)
    assert workout.name == "5/3/1"


def test_name_falls_back_to_dayname_only_when_program_missing():
    text = (
        '2026-01-15T10:00:00Z / dayName: "Push Day" / duration: 60s / exercises: {\n}'
    )
    workout = parse_liftohistory(text)
    assert workout.name == "Push Day"


def test_name_is_none_when_both_program_and_dayname_are_missing():
    text = "2026-01-15T10:00:00Z / duration: 60s / exercises: {\n}"
    workout = parse_liftohistory(text)
    assert workout.name is None


def test_elapsed_time_defaults_to_zero_when_duration_is_missing():
    text = "2026-01-15T10:00:00Z / exercises: {\n}"
    workout = parse_liftohistory(text)
    assert workout.elapsed_time == 0


def test_no_exercises_block_content_gives_an_empty_exercise_list():
    text = "2026-01-15T10:00:00Z / duration: 60s / exercises: {\n}"
    workout = parse_liftohistory(text)
    assert workout.exercises == []
