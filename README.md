# Trekking Management Application

A Flask, Jinja2, Bootstrap, and SQLite web application for managing trekking activities across three roles: Admin, Trek Staff, and Trekkers.

## Core Features

- Admin login with pre-created superuser account.
- Staff and trekker registration.
- Admin approval and blacklisting for staff/users.
- Trek creation, editing, removal, searching, and staff assignment.
- Staff dashboard for assigned treks, slots, status updates, and participant lists.
- Trekker dashboard for open treks, search/filter, booking, cancellation, profile edits, and history.
- SQLite database created programmatically on app startup.
- Booking validation prevents overbooking and allows booking only for `Open` treks.
- Trek statuses include `Pending`, `Approved`, `Open`, `Ongoing`, `Closed`, and `Completed`.
- `available_slots` is updated after booking and cancellation.

## Demo Admin

- Email: `admin@trek.local`
- Password: `admin123`

## Demo Staff and Trekker

- Staff email: `staff@trek.local`
- Staff password: `staff123`
- Trekker email: `user@trek.local`
- Trekker password: `user123`

The demo staff account is already approved by seed data.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
flask --app app run --debug
```

Open `http://127.0.0.1:5000`.

On Windows, you can also run `start-app.bat` after installing requirements.

The database is created automatically at `instance/trekking.db`.


