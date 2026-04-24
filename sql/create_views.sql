-- View 1: top_rated_workers

CREATE OR REPLACE VIEW view_top_rated_workers AS
SELECT 
    wp.worker_id, 
    u.full_name, 
    wp.average_rating, 
    wp.total_reviews, 
    COUNT(b.booking_id) AS completed_jobs
FROM worker_profile wp
JOIN Users u ON wp.worker_id = u.user_id
LEFT JOIN Bookings b ON wp.worker_id = b.worker_id AND b.status = 'Completed'
WHERE u.role = 'Worker' AND u.is_active = TRUE
GROUP BY wp.worker_id, u.full_name, wp.average_rating, wp.total_reviews
ORDER BY wp.average_rating DESC NULLS LAST;

-- View 2: open_jobs_by_city_service

CREATE OR REPLACE VIEW view_open_jobs_by_city_service AS
SELECT 
    j.job_id, 
    j.title, 
    j.city, 
    s.service_name, 
    j.created_at
FROM Jobs j
JOIN Services s ON j.service_id = s.service_id
WHERE j.status = 'Open'
ORDER BY j.created_at DESC;