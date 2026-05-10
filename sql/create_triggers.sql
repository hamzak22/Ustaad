-- Trigger 1: Auto-update Jobs status when a Booking happens
CREATE OR REPLACE FUNCTION sync_job_status_from_booking()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'Scheduled' THEN
        UPDATE Jobs SET status = 'In Progress' WHERE job_id = NEW.job_id;
    ELSIF NEW.status = 'Completed' THEN
        UPDATE Jobs SET status = 'Completed' WHERE job_id = NEW.job_id;
    ELSIF NEW.status = 'Cancelled' THEN
        UPDATE Jobs SET status = 'Open' WHERE job_id = NEW.job_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_sync_job_status
AFTER INSERT OR UPDATE OF status ON Bookings
FOR EACH ROW EXECUTE FUNCTION sync_job_status_from_booking();


-- Trigger 2: Auto-update worker ratings when a Review is posted, updated, or deleted
CREATE OR REPLACE FUNCTION update_worker_rating()
RETURNS TRIGGER AS $$
DECLARE
    v_worker_id UUID;
    v_new_avg_rating NUMERIC;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_worker_id := OLD.worker_id;
        
        -- Decrement total_reviews and recalculate average
        UPDATE worker_profile
        SET 
            total_reviews = GREATEST(0, total_reviews - 1),
            average_rating = COALESCE((SELECT ROUND(AVG(rating), 2) FROM Reviews WHERE worker_id = v_worker_id), 0.00)
        WHERE worker_id = v_worker_id;
        
    ELSIF TG_OP = 'INSERT' THEN
        v_worker_id := NEW.worker_id;
        
        -- Increment total_reviews and recalculate average
        UPDATE worker_profile
        SET 
            total_reviews = total_reviews + 1,
            average_rating = COALESCE((SELECT ROUND(AVG(rating), 2) FROM Reviews WHERE worker_id = v_worker_id), 0.00)
        WHERE worker_id = v_worker_id;
        
    ELSIF TG_OP = 'UPDATE' THEN
        v_worker_id := NEW.worker_id;
        
        -- Only recalculate average rating (total_reviews stays the same)
        UPDATE worker_profile
        SET 
            average_rating = COALESCE((SELECT ROUND(AVG(rating), 2) FROM Reviews WHERE worker_id = v_worker_id), 0.00)
        WHERE worker_id = v_worker_id;
    END IF;

    RETURN NULL; 
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_rating
AFTER INSERT OR UPDATE OR DELETE ON Reviews
FOR EACH ROW EXECUTE FUNCTION update_worker_rating();