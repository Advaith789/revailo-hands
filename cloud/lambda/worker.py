"""Per-page worker for the Part 2 demo.

Writes exactly one result per (job_id, page_no). The write is conditional on
the item not existing, so a Step Functions retry, a Lambda redelivery or a
whole new execution for the same job can never add a row or change a value:
the first write wins and every later one is a no-op that still succeeds.

The stand-in measurement is deterministic: area_sqft = page_no * 10.
"""

import json
import os

import boto3
from botocore.exceptions import ClientError

_client = None


def _dynamodb():
    global _client
    if _client is None:
        _client = boto3.client("dynamodb")
    return _client


def measure(page_no):
    return page_no * 10


def _parse(event):
    job_id = event.get("job_id")
    page_no = event.get("page_no")
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_id must be a non-empty string, got {!r}".format(job_id))
    # bool is a subclass of int; reject it explicitly.
    if isinstance(page_no, bool) or not isinstance(page_no, int) or page_no < 1:
        raise ValueError("page_no must be a positive integer, got {!r}".format(page_no))
    return job_id, page_no


def handler(event, context=None, client=None, table_name=None):
    job_id, page_no = _parse(event)
    area = measure(page_no)
    item = {
        "job_id": {"S": job_id},
        "page_no": {"N": str(page_no)},
        "area_sqft": {"N": str(area)},
        # Which execution wrote the row. A replay leaves this unchanged,
        # which is visible proof that the replay did not overwrite.
        "first_execution": {"S": str(event.get("execution", "unknown"))},
    }
    try:
        (client or _dynamodb()).put_item(
            TableName=table_name or os.environ["TABLE_NAME"],
            Item=item,
            ConditionExpression="attribute_not_exists(job_id)",
        )
        stored = True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        stored = False

    result = {"job_id": job_id, "page_no": page_no, "area_sqft": area, "stored": stored}
    print(json.dumps(result))
    return result
