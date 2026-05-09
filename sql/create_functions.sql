-- Procedure: assign_worker_to_request
CREATE OR REPLACE PROCEDURE assign_worker_to_request(
    p_bid_id UUID, 
    p_client_id UUID,
    OUT p_booking_id UUID 
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_id UUID;
    v_worker_id UUID;
    v_price NUMERIC;
    v_eta VARCHAR;
    v_actual_client_id UUID;
    v_job_status VARCHAR;
BEGIN
    
    SELECT b.job_id, b.worker_id, b.proposed_price, b.eta, j.client_id, j.status
    INTO v_job_id, v_worker_id, v_price, v_eta, v_actual_client_id, v_job_status
    FROM Bids b JOIN Jobs j ON b.job_id = j.job_id
    WHERE b.bid_id = p_bid_id
    FOR UPDATE OF j;  -- Lock job row to prevent race conditions

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Bid not found.';
    END IF;

    
    IF v_actual_client_id != p_client_id THEN
        RAISE EXCEPTION 'Only the job owner can accept this bid.';
    END IF;
    IF v_job_status != 'Open' THEN
        RAISE EXCEPTION 'Job is no longer open.';
    END IF;

    -- Guard: check if a booking already exists for this job (prevent double-accept)
    IF EXISTS (SELECT 1 FROM Bookings WHERE job_id = v_job_id) THEN
        RAISE EXCEPTION 'A booking already exists for this job.';
    END IF;

    
    -- mark selected bid accepted, reject others
    UPDATE Bids SET status = 'Accepted' WHERE bid_id = p_bid_id;
    UPDATE Bids SET status = 'Rejected' WHERE job_id = v_job_id AND bid_id != p_bid_id;

    -- update the job to reflect assignment and progress
    -- When a client accepts a bid on a public job we set the target_worker
    -- and convert the job to a Direct assignment so the table CHECK passes
    UPDATE Jobs
    SET status = 'In Progress', target_worker = v_worker_id, job_type = 'Direct'
    WHERE job_id = v_job_id;

    -- create booking (scheduled) and return id
    INSERT INTO Bookings (job_id, worker_id, agreed_price, eta, status)
    VALUES (v_job_id, v_worker_id, v_price, v_eta, 'Scheduled')
    RETURNING booking_id INTO p_booking_id;

END;
$$;