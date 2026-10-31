# INTRINSIC — Subscription & Invoicing Management

FastAPI + SQLAlchemy + SQLite backend, Tailwind CSS + Alpine.js frontend (single page, served by the API).

## Run
    pip install -r requirements.txt
    uvicorn main:app --reload
    # open http://127.0.0.1:8000   (Tailwind/Alpine load from CDN, so the browser needs internet)

The SQLite file `intrinsic.db` is created and seeded automatically on first start. Delete it to reseed.

## Demo accounts (also available as "Instant Persona Evaluation" buttons)
| Role     | Email                 | Password      |
|----------|-----------------------|---------------|
| Admin    | admin@intrinsic.io    | Admin@1234!   |
| Staff    | staff@intrinsic.io    | Staff@1234!   |
| Customer | customer@intrinsic.io | Customer@123! |

## Rules implemented
- Passwords: more than 8 characters, one uppercase, one lowercase, one special character (Pydantic + live frontend checklist).
- Public registration creates Customers only. Admins create Staff/Admin accounts in the Team tab (`POST /api/users`).
- Lifecycle: Draft -> Quotation -> Confirmed -> Active -> Closed (Closed can also be reached by cancelling from any open state).
- RBAC: Admin = everything; Staff = subscriptions, invoices, billing, read-only catalog; Customer = own subscriptions/invoices, may request a subscription (Draft), pay own invoices, cancel own subscription.
- Billing engine: `POST /api/billing/run` invoices every Active subscription whose next billing date is due, applies its discount, and marks late invoices Overdue.
- API docs: http://127.0.0.1:8000/docs
