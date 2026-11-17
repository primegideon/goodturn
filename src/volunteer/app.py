"""
GoodTurn Civic Aid - Volunteer Registry Service
Manages volunteer profile registrations, presence, and availability queries.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
VOLUNTEERS_TABLE = os.environ.get("VOLUNTEERS_TABLE")


def lambda_handler(event, context):
    logger.info("Received volunteer event: %s", json.dumps(event))

    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    }

    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": headers, "body": ""}

    try:
        table = dynamodb.Table(VOLUNTEERS_TABLE)

        if method == "GET":
            query_params = event.get("queryStringParameters") or {}
            district = query_params.get("district")

            if district:
                response = table.query(
                    IndexName="DistrictIndex",
                    KeyConditionExpression=Key("district").eq(district),
                )
                items = response.get("Items", [])
            else:
                response = table.scan(Limit=50)
                items = response.get("Items", [])

            return {
                "statusCode": 200,
                "headers": headers,
                "body": json.dumps({"items": items, "count": len(items)}),
            }

        elif method == "POST":
            raw_body = event.get("body", "{}")
            body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

            volunteer_id = body.get("volunteerId") or f"vol-{uuid.uuid4().hex[:8]}"
            name = body.get("name", "Civic Volunteer").strip()
            phone = body.get("phone", "").strip()
            district = body.get("district", "East Legon").strip()
            status = body.get("status", "AVAILABLE").strip()
            now = datetime.now(timezone.utc).isoformat()

            item = {
                "volunteerId": volunteer_id,
                "name": name,
                "phone": phone,
                "district": district,
                "status": status,
                "registeredAt": now,
                "lastActive": now,
            }

            table.put_item(Item=item)

            return {
                "statusCode": 201,
                "headers": headers,
                "body": json.dumps(item),
            }

        return {
            "statusCode": 405,
            "headers": headers,
            "body": json.dumps({"error": f"Method {method} not allowed"}),
        }

    except Exception as exc:
        logger.exception("Failed to process volunteer request")
        return {
            "statusCode": 500,
            "headers": headers,
            "body": json.dumps({"error": "Internal server error", "details": str(exc)}),
        }
