def test_workout_json_brief_is_id_name_date_and_window():
    from liftostrava.domain import Exercise, Set, Workout, WorkoutRecord
    from liftostrava_worker.routes.workout_json import workout_json

    entry = WorkoutRecord(
        id="42",
        workout=Workout(
            start_time="2026-10-31T09:00:00Z",
            elapsed_time=3600,
            exercises=[Exercise("Squat", [Set(5, 100.0), Set(5, 100.0)])],
            name="Lower Body Workout",
        ),
    )

    assert workout_json(entry, brief=True) == {
        "id": "42",
        "name": "Lower Body Workout",
        "date": "2026-10-31",
        "start": "2026-10-31T09:00:00Z",
        "end": "2026-10-31T10:00:00Z",
    }
    full = workout_json(entry, brief=False)
    assert full["duration_s"] == 3600
    assert full["exercises"] == [{"name": "Squat", "sets": 2}]
