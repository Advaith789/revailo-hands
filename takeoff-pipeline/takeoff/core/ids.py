import hashlib
import uuid


def new_job_id():
    return "job-" + uuid.uuid4().hex[:12]


def new_invocation_id():
    """Per-invocation identifier. In production this is the Lambda request
    id, which is what CloudWatch shows against every log line."""
    return uuid.uuid4().hex


def receipt(job_id, page_no, invocation_id):
    """Receipt for one stored page result.

    Receipts are the primary key of the results table and are what make the
    at-least-once delivery from the orchestrator safe to store.
    """
    raw = "/".join((str(job_id), str(page_no), str(invocation_id)))
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=12).hexdigest()
