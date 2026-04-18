CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS Users (
user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
full_name VARCHAR(100) NOT NULL,
email VARCHAR(255) NOT NULL UNIQUE,
password_hash VARCHAR(255) NOT NULL,
phone_number VARCHAR(20) NOT NULL UNIQUE,
role user_role_enum NOT NULL,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
is_active BOOLEAN DEFAULT TRUE
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
