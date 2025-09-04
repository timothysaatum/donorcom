# lambda_handler.py - Standalone Lambda handler
import os

# Force Lambda environment detection
os.environ["AWS_LAMBDA_FUNCTION_NAME"] = "true"

# Import the FastAPI app after setting environment
from main import app
from mangum import Mangum

# Create the Lambda handler
handler = Mangum(app, lifespan="off")

# Entry point for AWS Lambda
def lambda_handler(event, context):
    """
    AWS Lambda entry point
    Args:
        event: AWS Lambda event object
        context: AWS Lambda context object
    Returns:
        Response from FastAPI app via Mangum
    """
    return handler(event, context)