# Ustaad DBMS Checklist Audit and Implementation Plan

Date: 2026-04-22

## 1) Checklist Verification (Current State)

### Application Features

1. User Management (registration, login, role-based access)
- Status: Implemented
- Evidence:
  - Registration endpoint: modules/auth/routes.py (POST /auth/register)
  - Login endpoint: modules/auth/routes.py (POST /auth/token)
  - Role enum Customer/Worker: modules/auth/enums.py

2. Worker Profiles (experience, hourly rate, availability status)
- Status: Partially implemented
- Implemented:
  - Experience + bio creation in worker_profile via POST /auth/worker-profile
  - Hourly rate via worker_skills and update endpoint /workers/me
  - Availability enum exists in schema (availability_enum)
- Missing:
  - Availability is not exposed/updated through API models/routes
  - Profile response does not return availability

3. Service Catalog (predefined categories like plumbing/electrical)
- Status: Partially implemented
- Implemented:
  - Services table and read endpoints (/services, /services/{id})
- Missing:
  - No SQL seed data for predefined categories (plumbing, electrical, etc.)

4. Service Requests (customers can create/view/track)
- Status: Implemented
- Evidence:
  - Create job: modules/jobs/routes.py (POST /jobs/create)
  - View by id: modules/jobs/routes.py (GET /jobs/by-id/{job_id})
  - Customer tracking: modules/jobs/routes.py (GET /jobs/my-jobs includes status)

5. Worker Matching (workers retrieved by skills via SQL)
- Status: Implemented
- Evidence:
  - Skill-based filtering in job feed query using worker_skills subquery

6. Booking System (assign workers to requests)
- Status: Implemented
- Evidence:
  - Accept bid flow updates job status and inserts booking record

7. Review System (customers rate/review completed services)
- Status: Missing
- Missing:
  - No reviews table/entity
  - No review endpoints
  - No rating constraint (1..5) tied to review entries

### DBMS Highlights

8. Normalization to 3NF
- Status: Partially implemented / not documented
- Notes:
  - Core entities are separated (Users, Services, Jobs, Bids, Bookings, Worker_Skills)
  - No explicit 3NF documentation/proof in project
  - Potential redundancy exists (Jobs has city/location text while Locations table exists separately)

9. Constraints (PK/FK/UNIQUE/CHECK including rating 1..5)
- Status: Partially implemented
- Implemented:
  - PKs, FKs, UNIQUE(email/phone), CHECK(hourly_rate > 0), job and status constraints
- Missing:
  - Rating CHECK (1 to 5) absent because review table is absent
  - SQL script currently contains syntax issues in worker_profile and Saved_Jobs definitions that should be fixed before relying on migrations

10. Views (e.g., top-rated workers)
- Status: Missing

11. Triggers (auto status update on booking creation)
- Status: Missing
- Note:
  - Job status is updated in application code during bid acceptance, not as DB trigger

12. Stored Procedures (e.g., assign worker to request)
- Status: Missing
- Note:
  - Assignment logic exists in API transaction code, not encapsulated in DB routine

13. Indexing (frequently queried attributes)
- Status: Missing
- Note:
  - No explicit CREATE INDEX statements in sql scripts

## 2) Gaps to Close (Priority)

P0 (Critical for checklist completion)
1. Add Review system schema + APIs + validation (rating 1..5)
2. Add Views, Triggers, Stored Procedure scripts
3. Add explicit indexing strategy and CREATE INDEX statements
4. Fix SQL DDL syntax issues in create_tables.sql

P1 (Important quality/completeness)
1. Add service seed data (plumbing, electrical, carpentry, etc.)
2. Expose worker availability in profile APIs and updates
3. Add migration-safe SQL split files (tables, seed, views, triggers, procedures, indexes)

P2 (Documentation and verification)
1. Add 3NF justification section in README
2. Add end-to-end SQL verification script and API checklist tests

## 3) Implementation Plan (Phased)

### Phase 1: Schema Corrections and Missing Core Entities
1. Fix create_tables.sql syntax errors
2. Add Reviews table:
- review_id UUID PK
- booking_id UUID UNIQUE FK -> Bookings
- job_id UUID FK -> Jobs
- customer_id UUID FK -> Users
- worker_id UUID FK -> worker_profile
- rating INT CHECK (rating BETWEEN 1 AND 5)
- comment TEXT
- created_at TIMESTAMP
3. Add guard constraints:
- One review per completed booking
- Optional CHECK to enforce booking status completed before review (or enforce in trigger)

### Phase 2: DBMS Artifacts
1. Add Views:
- top_rated_workers (avg rating, total reviews, completed jobs)
- open_jobs_by_city_service
2. Add Trigger(s):
- On Bookings INSERT/UPDATE: sync Jobs.status (Open -> In Progress -> Completed/Cancelled)
- On Reviews INSERT/UPDATE/DELETE: update worker_profile.average_rating and total_reviews
3. Add Stored Procedure / Function:
- assign_worker_to_request(p_bid_id UUID, p_client_id UUID)
- Encapsulate: ownership checks, bid status updates, booking insert, job status transition

### Phase 3: Performance and Seed Data
1. Add indexes:
- Users(email)
- Jobs(client_id, status, city, service_id, created_at)
- Worker_Skills(worker_id, service_id)
- Bids(job_id, worker_id, status)
- Bookings(worker_id, status)
- Reviews(worker_id, rating)
2. Add seed SQL for Services:
- Plumbing, Electrical, Carpentry, AC Repair, Cleaning, Painting

### Phase 4: API Feature Completion
1. Review endpoints:
- POST /reviews (customer can review completed booking)
- GET /workers/{id}/reviews
- GET /workers/top-rated (from SQL view)
2. Worker availability support:
- Include availability in profile response
- Add update field in worker profile update model/route
3. Align API and DB transactional logic with stored procedure usage

### Phase 5: Validation and Documentation
1. Add README checklist mapping each requirement to endpoint/SQL object
2. Add SQL smoke tests for views/triggers/procedures
3. Add API test collection (happy path + auth/constraint failures)

## 4) Suggested Deliverables to Submit

1. sql/create_tables.sql (fixed + Reviews table)
2. sql/seed_services.sql
3. sql/create_views.sql
4. sql/create_triggers.sql
5. sql/create_functions.sql
6. sql/create_indexes.sql
7. Updated route/model files for reviews and availability
8. README section: "DBMS Checklist Compliance"

## 5) Fast Execution Order (1 sprint)

Day 1
1. Fix DDL syntax
2. Add Reviews table + seed services
3. Add indexes

Day 2
1. Add view + trigger + stored procedure
2. Add review APIs

Day 3
1. Add availability API support
2. Testing + README compliance table
