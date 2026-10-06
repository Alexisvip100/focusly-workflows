from app.modules.google_calendar.routes import event_attendees


def test_event_attendees_keeps_every_guest_with_their_answer():
    item = {
        "attendees": [
            {
                "email": "yo@example.com",
                "self": True,
                "organizer": True,
                "responseStatus": "accepted",
            },
            {"email": "ana@example.com", "responseStatus": "declined"},
            {"displayName": "Sin correo"},
        ]
    }
    assert event_attendees(item) == [
        {
            "email": "yo@example.com",
            "responseStatus": "accepted",
            "self": True,
            "organizer": True,
        },
        {
            "email": "ana@example.com",
            "responseStatus": "declined",
            "self": False,
            "organizer": False,
        },
    ]


def test_event_attendees_without_guests():
    assert event_attendees({}) == []
