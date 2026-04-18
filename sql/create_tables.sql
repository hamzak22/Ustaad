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
bio TEXT
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
    job_id uuid PRIMARY KEY uuid_generate_v4(),
    client_id uuid NOT NULL REFERENCES Users(user_id) ON DELETE CASCADE,
    service_id uuid NOT NULL REFERENCES Services(service_id),
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    job_type job_type_enum NOT NULL DEFAULT 'Public',
    target_worker uuid REFERENCES worker_profile(worker_id),
    location_address TEXT NOT NULL DEFAULT 'Unspecified',
    status job_status_enum NOT NULL DEFAULT 'Open',
    estimated_budget NUMERIC(10,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT check_job_type CHECK (
        (job_type == 'Direct' AND target_worker IS NOT NULL) OR 
        (job_type =='Public' AND target_worker IS NULL)
    ) 
);
