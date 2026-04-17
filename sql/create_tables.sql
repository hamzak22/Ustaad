CREATE TABLE Users (
user_id SERIAL PRIMARY KEY,
full_name VARCHAR(100) NOT NULL,
email VARCHAR(255) NOT NULL UNIQUE,
password_hash VARCHAR(255) NOT NULL,
phone_number VARCHAR(20) NOT NULL UNIQUE,
role user_role_enum NOT NULL,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE worker_profile(
worker_id INT PRIMARY KEY,
experience INT NOT NULL,
hourly_rate FLOAT NOT NULL,
availability availability_enum DEFAULT 'Available',
bio TEXT
);
