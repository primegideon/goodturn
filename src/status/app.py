"""
GoodTurn Civic Aid - Request Query & Status Service
Provides endpoints to query individual requests or list errand dispatches
with support for filtering by district and status.
"""

import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
REQUESTS_TABLE = os.environ.get("REQUESTS_TABLE")


def lambda_handler(event, context):
    logger.info("Received query event: %s", json.dumps(event))

    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    }

    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return {"statusCode": 200, "headers": headers, "body": ""}

    try:
        table = dynamodb.Table(REQUESTS_TABLE)
        path_params = event.get("pathParameters") or {}
        request_id = path_params.get("requestId")

        # Single request lookup
        if request_id:
            response = table.get_item(Key={"requestId": request_id})
            item = response.get("Item")
            if not item:
                return {
                    "statusCode": 404,
                    "headers": headers,
                    "body": json.dumps({"error": f"Request {request_id} not found"}),
                }
            # Mask internal task tokens from client response
            item.pop("matchTaskToken", None)
            item.pop("verificationTaskToken", None)
            return {
                "statusCode": 200,
                "headers": headers,
                "body": json.dumps(item),
            }

        # Multi-request list query
        query_params = event.get("queryStringParameters") or {}
        district = query_params.get("district")
        status_filter = query_params.get("status")

        if district:
            response = table.query(
                IndexName="DistrictIndex",
                KeyConditionExpression=Key("district").eq(district),
                ScanIndexForward=False,
                Limit=50,
            )
            items = response.get("Items", [])
        elif status_filter:
            response = table.query(
                IndexName="StatusIndex",
                KeyConditionExpression=Key("status").eq(status_filter),
                ScanIndexForward=False,
                Limit=50,
            )
            items = response.get("Items", [])
        else:
            response = table.scan(Limit=50)
            items = response.get("Items", [])

        # Clean sensitive or internal orchestration tokens
        for item in items:
            item.pop("matchTaskToken", None)
            item.pop("verificationTaskToken", None)

        return {
            "statusCode": 200,
            "headers": headers,
            "body": json.dumps({"items": items, "count": len(items)}),
        }

    except Exception as exc:
        logger.exception("Failed to query requests")
        return {
            "statusCode": 500,
            "headers": headers,
            "body": json.dumps({"error": "Internal server error", "details": str(exc)}),
        }
