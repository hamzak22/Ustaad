CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS Users (
user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
full_name VARCHAR(100) NOT NULL,
email VARCHAR(255) NOT NULL UNIQUE,
password_hash VARCHAR(255) NOT NULL,
phone_number VARCHAR(20) NOT NULL UNIQUE,
role user_role_enum NOT NULL,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
city VARCHAR(100) NOT NULL DEFAULT 'Unspecified',
is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS RefreshTokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES Users(user_id) ON DELETE CASCADE,
    token_text TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS worker_profile(
worker_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
experience INT NOT NULL,
availability availability_enum DEFAULT 'Available',
bio TEXT,
average_rating NUMERIC(3, 2) DEFAULT 0.00,
total_reviews INT DEFAULT 0;
);

CREATE TABLE IF NOT EXISTS Services (
    service_id uuid PRIMARY KEY default uuid_generate_v4(),    
    service_name VARCHAR(100) NOT NULL UNIQUE, 
    description TEXT
);

CREATE TABLE IF NOT EXISTS Worker_Skills (
    worker_id UUID NOT NULL REFERENCES Worker_Profile(worker_id) ON DELETE CASCADE,
    service_id UUID NOT NULL REFERENCES Services(service_id) ON DELETE CASCADE,
    hourly_rate NUMERIC(10,2) NOT NULL CHECK (hourly_rate > 0),
    
    PRIMARY KEY (worker_id, service_id)
);

CREATE TABLE IF NOT EXISTS Jobs (
    job_id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id uuid NOT NULL REFERENCES Users(user_id) ON DELETE CASCADE,
    service_id uuid NOT NULL REFERENCES Services(service_id),
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    job_type job_type_enum NOT NULL DEFAULT 'Public',
    target_worker uuid REFERENCES worker_profile(worker_id),
    location_address TEXT NOT NULL DEFAULT 'Unspecified',
    city VARCHAR(100) NOT NULL DEFAULT 'Unspecified',
    status job_status_enum NOT NULL DEFAULT 'Open',
    estimated_budget NUMERIC(10,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT check_job_type CHECK (
        (job_type = 'Direct' AND target_worker IS NOT NULL) OR 
        (job_type ='Public' AND target_worker IS NULL)
    ) 
);

CREATE TABLE IF NOT EXISTS Locations (

CREATE TABLE IF NOT EXISTS Bid_Attached_Reviews (
    bid_id UUID NOT NULL REFERENCES Bids(bid_id) ON DELETE CASCADE,
    review_id UUID NOT NULL REFERENCES Reviews(review_id) ON DELETE CASCADE,
    PRIMARY KEY (bid_id, review_id)
);
    location_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS Bids (
    bid_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL REFERENCES Jobs(job_id) ON DELETE CASCADE,
    worker_id UUID NOT NULL REFERENCES worker_profile(worker_id),
    proposed_price NUMERIC(10, 2) NOT NULL,
    fee_type fee_type_enum NOT NULL DEFAULT 'Flat',
    eta VARCHAR(100) NOT NULL,            -- could be 1 hour or 2 days
    description TEXT,                     -- Optional comments / cover letter
    status VARCHAR(20) DEFAULT 'Pending' CHECK (status IN ('Pending', 'Accepted', 'Rejected')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (job_id, worker_id)            
);

CREATE TABLE IF NOT EXISTS Bid_Attached_Reviews (
    bid_id UUID NOT NULL REFERENCES Bids(bid_id) ON DELETE CASCADE,
    review_id UUID NOT NULL REFERENCES Reviews(review_id) ON DELETE CASCADE,
    PRIMARY KEY (bid_id, review_id)
);

CREATE TABLE IF NOT EXISTS Bookings (
    booking_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL UNIQUE REFERENCES Jobs(job_id),
    worker_id UUID NOT NULL REFERENCES worker_profile(worker_id),
    agreed_price NUMERIC(10, 2) NOT NULL,
    eta VARCHAR(100) NOT NULL,
    status VARCHAR(20) DEFAULT 'Scheduled' CHECK (status IN ('Scheduled', 'In Progress', 'Completed', 'Cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );


CREATE TABLE IF NOT EXISTS Saved_Jobs(
	id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
	job_id UUID NOT NULL references jobs(job_id),
	worker_id UUID NOT NULL references worker_profile(worker_id),

	CONSTRAINT unique_saved_job UNIQUE(job_id, worker_id)
);

CREATE TABLE IF NOT EXISTS Direct_Job_Responses (
	id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
	job_id UUID NOT NULL REFERENCES Jobs(job_id) ON DELETE CASCADE,
	worker_id UUID NOT NULL REFERENCES worker_profile(worker_id) ON DELETE CASCADE,
	response_status VARCHAR(20) NOT NULL CHECK (response_status IN ('Accepted', 'Declined')),
	responded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	CONSTRAINT unique_direct_response UNIQUE(job_id, worker_id)
);



CREATE TABLE IF NOT EXISTS Reviews (
    review_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    booking_id UUID NOT NULL UNIQUE REFERENCES Bookings(booking_id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES Jobs(job_id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES Users(user_id),
    worker_id UUID NOT NULL REFERENCES worker_profile(worker_id),
    rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5), 
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Notifications (
    notification_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    recipient_id UUID NOT NULL REFERENCES Users(user_id) ON DELETE CASCADE,
    actor_id UUID REFERENCES Users(user_id) ON DELETE SET NULL,
    notification_type notification_type_enum NOT NULL,
    title VARCHAR(150) NOT NULL,
    body TEXT NOT NULL,
    entity_type VARCHAR(50),
    entity_id UUID,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    read_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notifications_recipient_read_created
    ON Notifications (recipient_id, is_read, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_notifications_recipient_created
    ON Notifications (recipient_id, created_at DESC);

ALTER TABLE worker_profile
ADD COLUMN availability_status VARCHAR(20) DEFAULT 'Available' CHECK (availability_status IN ('Available', 'Busy', 'Offline'));


