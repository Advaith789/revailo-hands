"""Local checks for the worker's idempotency logic, with an in-memory stand-in
for DynamoDB's conditional PutItem. Run: python -m pytest cloud/lambda"""

import pytest
from botocore.exceptions import ClientError

import worker


class FakeDynamo(object):
    def __init__(self):
        self.items = {}

    def put_item(self, TableName, Item, ConditionExpression):
        assert ConditionExpression == "attribute_not_exists(job_id)"
        key = (Item["job_id"]["S"], Item["page_no"]["N"])
        if key in self.items:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}},
                "PutItem",
            )
        self.items[key] = Item


def test_first_write_stores_page_times_ten():
    db = FakeDynamo()
    out = worker.handler({"job_id": "j", "page_no": 3, "execution": "e1"}, client=db, table_name="t")
    assert out == {"job_id": "j", "page_no": 3, "area_sqft": 30, "stored": True}
    assert db.items[("j", "3")]["area_sqft"] == {"N": "30"}


def test_replay_succeeds_without_changing_the_row():
    db = FakeDynamo()
    worker.handler({"job_id": "j", "page_no": 2, "execution": "e1"}, client=db, table_name="t")
    out = worker.handler({"job_id": "j", "page_no": 2, "execution": "e2"}, client=db, table_name="t")
    assert out["stored"] is False
    assert len(db.items) == 1
    assert db.items[("j", "2")]["first_execution"] == {"S": "e1"}


def test_other_dynamodb_errors_propagate():
    class Broken(object):
        def put_item(self, **kw):
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "PutItem")

    with pytest.raises(ClientError):
        worker.handler({"job_id": "j", "page_no": 1}, client=Broken(), table_name="t")


@pytest.mark.parametrize("event", [
    {"job_id": "", "page_no": 1},
    {"job_id": "j", "page_no": 0},
    {"job_id": "j", "page_no": "1"},
    {"job_id": "j", "page_no": True},
    {"page_no": 1},
])
def test_bad_input_is_rejected(event):
    with pytest.raises(ValueError):
        worker.handler(event, client=FakeDynamo(), table_name="t")
