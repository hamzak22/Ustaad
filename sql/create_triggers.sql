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


-- Trigger 2: Auto-update worker ratings when a Review is posted
CREATE OR REPLACE FUNCTION update_worker_rating()
RETURNS TRIGGER AS $$
DECLARE
    v_worker_id UUID;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_worker_id := OLD.worker_id;
    ELSE
        v_worker_id := NEW.worker_id;
    END IF;

    UPDATE worker_profile
    SET 
        average_rating = COALESCE((SELECT ROUND(AVG(rating), 2) FROM Reviews WHERE worker_id = v_worker_id), 0.00),
        total_reviews = (SELECT COUNT(*) FROM Reviews WHERE worker_id = v_worker_id)
    WHERE worker_id = v_worker_id;

    RETURN NULL; 
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_rating
AFTER INSERT OR UPDATE OR DELETE ON Reviews
FOR EACH ROW EXECUTE FUNCTION update_worker_rating();