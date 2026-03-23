# Food Waste Distribution Web Application

A role-based web platform where donors can post surplus food and NGOs can claim and collect it.

## Tech Stack
- Frontend: HTML, Tailwind CSS, Vanilla JavaScript
- Backend: Flask (Python)
- Database: MongoDB (PyMongo)
- Template Engine: Jinja2 

## Features
- Web-based platform (currently no Android/iOS app)
- Username/password authentication with hashed passwords
- Role-based registration (`donor` or `ngo`)
- Session-based login management
- Protected routes with role checks
- Donor food listing CRUD and status workflow
- NGO filtering, claim flow, and receive confirmation
- Two-way in-app messaging between donor and NGO
- Project-only chatbot with API key auto-rotation
- Flash messages for success/error feedback
- Responsive UI with donor (green) and NGO (blue) themes

## Project Structure
```
.
├── app.py
├── config.py
├── requirements.txt
├── .env
├── static/
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── app.js
└── templates/
   ├── base.html
   ├── auth/
   │   ├── login.html
   │   └── register.html
   ├── donor/
   │   ├── dashboard.html
   │   └── add_food.html
   └── ngo/
      ├── dashboard.html
      └── claim_food.html
```

## MongoDB Collections
### `users`
- `username`
- `password` (hashed)
- `role`
- `organization_name`
- `location`
- `contact`
- `created_at`

### `food_listings`
- `donor_id`
- `food_name`
- `quantity`
- `donation_price` (required, low-cost donation rate per unit)
- `expiry`
- `location`
- `description`
- `category`
- `status` (`available`, `claimed`, `collected`)
- `claimed_by`
- `created_at`

### `messages`
- `sender_id`
- `recipient_id`
- `sender_role`
- `recipient_role`
- `listing_id` (optional)
- `message`
- `is_read`
- `created_at`

## Setup Instructions
1. Open terminal and move to project folder:
   ```bash
   cd E:\folder\peanuts\ceosus\fwd
   ```
2. Create and activate virtual environment:
   ```bash
   python -m venv .venv
   # Windows PowerShell
   .\.venv\Scripts\Activate.ps1
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure environment variables in `.env`:
   ```env
   SECRET_KEY=replace-with-a-strong-secret-key

   # Option A: Full URI
   MONGO_URI=mongodb://localhost:27017
   MONGO_DB_NAME=foodwaste_db

   # Option B: Split Mongo Atlas values
   MONGO_USERNAME=your_username
   MONGO_PASSWORD=your_password
   MONGO_CLUSTER=cluster0.xxxxx.mongodb.net
   MONGO_DATABASE=foodwaste_db

   # Donation price business rule
   # false (default): price must be > 0
   # true: price can be 0 or greater
   DONATION_PRICE_ALLOW_ZERO=false

   # Chatbot keys (any of these names are supported)
   FWD_API_KEY_1=your_key_1
   FWD_API_KEY_2=your_key_2
   FWD_API_KEY_3=your_key_3

   # Alternate key names also supported
   fwd_1_api=your_key_1
   fwd_2_api=your_key_2
   fwd_3_api=your_key_3
   ```
5. Ensure MongoDB is running locally (Option A) or configure Atlas credentials (Option B).
6. Run the Flask app:
   ```bash
   python app.py
   ```
7. Open in browser:
   ```
   http://127.0.0.1:5000
   ```

## Default Route Flow
- `/register` -> Create donor or NGO account
- `/login` -> Authenticate user
- Donor -> `/donor/dashboard`
- NGO -> `/ngo/dashboard`
- Authenticated users -> `/chatbot` for project-restricted Q&A

## Testing
The project now includes test coverage at four levels using `pytest` and an in-memory Mongo mock.

### Install Test Dependencies
```bash
pip install -r requirements-test.txt
```

### Run Unit Tests
Validates pure functions and small isolated logic.
```bash
pytest tests/unit
```

### Run Integration Tests
Validates module interactions such as auth flow and session behavior.
```bash
pytest tests/integration
```

### Run System Tests
Validates full workflow across major modules (donor listing -> NGO claim -> received).
```bash
pytest tests/system
```

### Run Acceptance Tests
Validates user-story behavior from an end-user point of view.
```bash
pytest tests/acceptance
```

### Run Complete Test Suite
```bash
pytest
```

## Security Notes
- Passwords are hashed using Werkzeug.
- Sessions use Flask secret key.
- Route decorators enforce authentication and role authorization.

## Chatbot Dataset (Review Format)
The chatbot is now grounded with an FWD-relevant dataset stored at `data/fwd_chatbot_dataset.json`.

This dataset is used as runtime knowledge context so responses stay aligned with the current FWD web application.

### Dataset Coverage
| Intent | What it teaches the chatbot |
|---|---|
| Platform Scope | FWD is web-based only, no app-store flow |
| Account Creation | Register flow and role selection |
| Login | Username/password web login and dashboard redirect |
| Registration Fields | Required registration fields in current build |
| Donor Listing | How donors create listings |
| Donation Pricing | Low-cost donation model (not free) |
| NGO Claim Flow | NGO claim steps and availability workflow |
| Collection Status | Status transitions (`available -> claimed -> collected`) |
| Messaging | In-app donor/NGO conversation support |
| Map and Distance | Address search, map pinning, distance guidance |
| Chatbot Scope | Project-only support behavior |
| Notifications | Current web limitations for push/email app notifications |
| Acknowledgement Handling | Context-aware replies for short turns like okay/thanks |
| Greeting Handling | FWD-specific welcome replies (not generic resets) |

### Dataset Entries (Current)
1. Platform Scope: "FWD is currently web-based only..."
2. Account Creation: "Register page -> role -> username/password/org/location/contact"
3. Login: "Username/password login routes to role dashboard"
4. Registration Fields: "Current required fields and no app-download step"
5. Donor Listing: "Add food with quantity, price, expiry, location"
6. Donation Pricing: "Low-cost donation pricing (default > 0, optional config allows 0)"
7. NGO Claim Flow: "Browse available listings and claim"
8. Collection Status: "available -> claimed -> collected"
9. Messaging: "Two-way in-app donor/NGO messaging"
10. Map and Distance: "Map pin, address suggestions, distance/ETA guidance"
11. Chatbot Scope: "FWD-only questions"
12. Notifications: "No native app push in current web build"
13. Acknowledgement Handling: "Short acknowledgements return FWD-specific next-help options"
14. Greeting Handling: "Greetings return FWD workflow-focused support guidance"

### How "Training" Is Applied Here
- Current implementation uses grounding (dataset-backed context injection) per question.
- This avoids hallucinations like app-store/email-login instructions that do not match FWD.
- If you want full model fine-tuning later, this same dataset can be exported to JSONL instruction format.

## Optional Improvements
- Add CSRF protection with Flask-WTF
- Add pagination and richer analytics
- Add SMS or WhatsApp notifications for claims
- Add expiry alerts and scheduled cleanup jobs

## Maintenance / Coming Soon Mode
You can temporarily show a "Coming Soon" page for the deployed site while backend updates are in progress.

Set this environment variable in deployment:
```env
MAINTENANCE_MODE=true
```

When enabled:
- Most routes return the maintenance page.
- Static assets and legal/contact pages stay reachable.
- You can also open `/coming-soon` directly.

To restore normal site behavior, set:
```env
MAINTENANCE_MODE=false
```
