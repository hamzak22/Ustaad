CREATE TYPE user_role_enum AS ENUM ('Customer', 'Worker');

CREATE TYPE availability_enum AS ENUM('Available', 'Busy', 'Offline');

CREATE TYPE job_type_enum AS ENUM ('Public', 'Direct');
CREATE TYPE job_status_enum AS ENUM ('Open', 'In Progress', 'Completed', 'Cancelled');
CREATE TYPE bid_status_enum AS ENUM ('Pending', 'Accepted', 'Rejected');
CREATE TYPE booking_status_enum AS ENUM ('Scheduled', 'Completed', 'Cancelled');

