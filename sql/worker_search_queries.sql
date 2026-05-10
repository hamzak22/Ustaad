-- Worker Profile Search Queries

-- Query 1: Search workers by service (skill) with optional filters
-- Parameters: service_id (required), city, min_rating, availability, limit, offset
-- Returns: worker profile with user details and service rate
SELECT 
    u.user_id,
    u.full_name,
    u.email,
    u.phone_number,
    u.city,
    wp.worker_id,
    wp.experience,
    wp.availability,
    wp.bio,
    wp.average_rating,
    (SELECT COALESCE(COUNT(*), 0) FROM Reviews WHERE worker_id = wp.worker_id) AS total_reviews,
    ws.service_id,
    s.service_name,
    ws.hourly_rate
FROM Users u
JOIN worker_profile wp ON u.user_id = wp.worker_id
JOIN worker_skills ws ON wp.worker_id = ws.worker_id
JOIN Services s ON ws.service_id = s.service_id
WHERE 
    ws.service_id = $1::UUID
    AND u.is_active = true
    AND (wp.availability = $2::VARCHAR OR $2::VARCHAR IS NULL)  -- filter by availability if provided
    AND (u.city = $3::VARCHAR OR $3::VARCHAR IS NULL)  -- filter by city if provided
    AND wp.average_rating >= COALESCE($4, 0)  -- minimum rating filter
ORDER BY wp.average_rating DESC, u.full_name ASC
LIMIT $5 OFFSET $6;


-- Query 2: Search workers by multiple criteria (advanced search)
-- Parameters: service_id, city, min_rating, availability, limit, offset
-- Returns: unique workers with their best-rated service for this criterion
SELECT DISTINCT ON (wp.worker_id)
    u.user_id,
    u.full_name,
    u.email,
    u.phone_number,
    u.city,
    wp.worker_id,
    wp.experience,
    wp.availability,
    wp.bio,
    wp.average_rating,
    (SELECT COALESCE(COUNT(*), 0) FROM Reviews WHERE worker_id = wp.worker_id) AS total_reviews,
    ws.service_id,
    s.service_name,
    ws.hourly_rate
FROM Users u
JOIN worker_profile wp ON u.user_id = wp.worker_id
JOIN worker_skills ws ON wp.worker_id = ws.worker_id
JOIN Services s ON ws.service_id = s.service_id
WHERE 
    u.is_active = true
    AND (ws.service_id = $1::UUID OR $1::UUID IS NULL)  -- filter by service if provided
    AND (u.city = $2::VARCHAR OR $2::VARCHAR IS NULL)  -- filter by city if provided
    AND wp.average_rating >= COALESCE($3, 0)  -- minimum rating filter
    AND (wp.availability = $4::VARCHAR OR $4::VARCHAR IS NULL)  -- filter by availability if provided
ORDER BY wp.worker_id, wp.average_rating DESC
LIMIT $5 OFFSET $6;


-- Query 3: Get detailed worker profile (for customer view)
-- Parameters: worker_id
-- Returns: complete worker profile with all skills and ratings
SELECT 
    u.user_id,
    u.full_name,
    u.email,
    u.phone_number,
    u.city,
    u.created_at,
    wp.worker_id,
    wp.experience,
    wp.availability,
    wp.bio,
    wp.average_rating,
    (SELECT COALESCE(COUNT(*), 0) FROM Reviews WHERE worker_id = wp.worker_id) AS total_reviews,
    json_agg(
        json_build_object(
            'service_id', s.service_id,
            'service_name', s.service_name,
            'hourly_rate', ws.hourly_rate
        )
    ) AS skills
FROM Users u
JOIN worker_profile wp ON u.user_id = wp.worker_id
LEFT JOIN worker_skills ws ON wp.worker_id = ws.worker_id
LEFT JOIN Services s ON ws.service_id = s.service_id
WHERE 
    wp.worker_id = $1::UUID
    AND u.is_active = true
GROUP BY u.user_id, u.full_name, u.email, u.phone_number, u.city, 
         u.created_at, wp.worker_id, wp.experience, wp.availability,
         wp.bio, wp.average_rating;


-- Query 4: Get worker's recent reviews (for customer view)
-- Parameters: worker_id
-- Returns: reviews from jobs completed by this worker
SELECT 
    r.review_id,
    r.rating,
    r.comment,
    r.created_at,
    u.full_name AS customer_name,
    j.title AS job_title
FROM Reviews r
JOIN Jobs j ON r.job_id = j.job_id
JOIN Users u ON r.customer_id = u.user_id
WHERE r.worker_id = $1::UUID
ORDER BY r.created_at DESC
LIMIT 10;


-- Query 5: Search workers by name and service (text search)
-- Parameters: search_query, service_id (optional), limit, offset
-- Returns: workers matching search criteria ranked by relevance
SELECT 
    u.user_id,
    u.full_name,
    u.email,
    u.phone_number,
    u.city,
    wp.worker_id,
    wp.experience,
    wp.availability,
    wp.bio,
    wp.average_rating,
    (SELECT COALESCE(COUNT(*), 0) FROM Reviews WHERE worker_id = wp.worker_id) AS total_reviews,
    ws.service_id,
    s.service_name,
    ws.hourly_rate,
    -- Relevance scoring (full name match gets higher score)
    CASE 
        WHEN LOWER(u.full_name) = LOWER($1) THEN 3
        WHEN LOWER(u.full_name) LIKE LOWER($1 || '%') THEN 2
        WHEN LOWER(u.full_name) ILIKE $1 THEN 1
        ELSE 0
    END AS relevance_score
FROM Users u
JOIN worker_profile wp ON u.user_id = wp.worker_id
JOIN worker_skills ws ON wp.worker_id = ws.worker_id
JOIN Services s ON ws.service_id = s.service_id
WHERE 
    u.is_active = true
    AND (LOWER(u.full_name) ILIKE '%' || LOWER($1) || '%' OR LOWER(wp.bio) ILIKE '%' || LOWER($1) || '%')
    AND (ws.service_id = $2::UUID OR $2::UUID IS NULL)
ORDER BY relevance_score DESC, wp.average_rating DESC
LIMIT $3 OFFSET $4;


-- Query 6: Get availability count by worker (for quick stats)
-- Parameters: none
-- Returns: count of workers by availability status
SELECT 
    availability,
    COUNT(*) AS worker_count
FROM worker_profile
GROUP BY availability;
