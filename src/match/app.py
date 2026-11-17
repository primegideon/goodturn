"""
GoodTurn Civic Aid - Dispatch and Step Functions Callback Registrar
Invoked by AWS Step Functions to register task tokens and coordinate volunteer dispatch.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
REQUESTS_TABLE = os.environ.get("REQUESTS_TABLE")
VOLUNTEERS_TABLE = os.environ.get("VOLUNTEERS_TABLE")


def lambda_handler(event, context):
    logger.info("MatchFunction invoked with payload: %s", json.dumps(event))

    action = event.get("action", "AWAIT_ACCEPTANCE")
    request_id = event.get("requestId")
    task_token = event.get("taskToken")
    district = event.get("district")

    if not request_id or not task_token:
        logger.error("Missing required requestId or taskToken")
        raise ValueError("requestId and taskToken are required")

    requests_table = dynamodb.Table(REQUESTS_TABLE)
    now = datetime.now(timezone.utc).isoformat()

    if action == "AWAIT_ACCEPTANCE":
        # Query active volunteers in the matching district
        matched_volunteers = []
        if VOLUNTEERS_TABLE and district:
            try:
                volunteers_table = dynamodb.Table(VOLUNTEERS_TABLE)
                response = volunteers_table.query(
                    IndexName="DistrictIndex",
                    KeyConditionExpression=Key("district").eq(district),
                )
                matched_volunteers = response.get("Items", [])
                logger.info(
                    "Identified %d potential volunteers in district %s",
                    len(matched_volunteers),
                    district,
                )
            except Exception as query_err:
                logger.warning("Could not query volunteers index: %s", str(query_err))

        # Store the task token on the request item in DynamoDB
        requests_table.update_item(
            Key={"requestId": request_id},
            UpdateExpression="SET matchTaskToken = :token, status = :status, dispatchedAt = :now, candidateCount = :count",
            ExpressionAttributeValues={
                ":token": task_token,
                ":status": "PENDING_MATCH",
                ":now": now,
                ":count": len(matched_volunteers),
            },
        )
        logger.info("Saved matchTaskToken for request %s", request_id)

    elif action == "AWAIT_VERIFICATION":
        # Store the delivery verification task token
        requests_table.update_item(
            Key={"requestId": request_id},
            UpdateExpression="SET verificationTaskToken = :token, status = :status, handoffPendingAt = :now",
            ExpressionAttributeValues={
                ":token": task_token,
                ":status": "MATCHED",
                ":now": now,
            },
        )
        logger.info("Saved verificationTaskToken for request %s", request_id)

    return {
        "statusCode": 200,
        "action": action,
        "requestId": request_id,
        "registered": True,
    }
