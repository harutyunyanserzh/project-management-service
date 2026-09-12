# Lambda Functions

Two functions, triggered by S3 `ObjectCreated` events on the documents bucket.

## `size_limit/handler.py` (required by spec)

Sums the total size of a project's documents on every upload and deletes
the object that pushes the project over `MAX_PROJECT_STORAGE_BYTES` (default
100 MB, configurable via an environment variable of the same name on the
Lambda function itself).

## `image_resize/handler.py` (optional per spec)

Placeholder for future image-attachment support: generates a thumbnail for
any uploaded `.png`/`.jpg`/`.jpeg` object. Not exercised by the current app
(documents are pdf/docx only), included to satisfy the optional spec item.

---

## Deploying (once your AWS sandbox credentials are active)

Repeat for each function (`size_limit`, and optionally `image_resize`):

```bash
cd lambda_functions/size_limit
pip install -r requirements.txt -t package --break-system-packages
cp handler.py package/
cd package && zip -r ../function.zip . && cd ..

aws lambda create-function \
  --function-name project-management-size-limit \
  --runtime python3.10 \
  --handler handler.handler \
  --zip-file fileb://function.zip \
  --role <YOUR_SANDBOX_EXECUTION_ROLE_ARN> \
  --environment "Variables={MAX_PROJECT_STORAGE_BYTES=104857600}" \
  --region us-east-1
```

Replace `<YOUR_SANDBOX_EXECUTION_ROLE_ARN>` with the role ARN your sandbox
provides (often something like `LabRole` — sandboxes typically don't let you
create new IAM roles, so you must reuse the provided one).

### Wiring up the S3 trigger

```bash
aws lambda add-permission \
  --function-name project-management-size-limit \
  --principal s3.amazonaws.com \
  --statement-id s3invoke \
  --action "lambda:InvokeFunction" \
  --source-arn arn:aws:s3:::<YOUR_BUCKET_NAME> \
  --region us-east-1

aws s3api put-bucket-notification-configuration \
  --bucket <YOUR_BUCKET_NAME> \
  --notification-configuration '{
    "LambdaFunctionConfigurations": [
      {
        "LambdaFunctionArn": "<FUNCTION_ARN_FROM_CREATE_FUNCTION_OUTPUT>",
        "Events": ["s3:ObjectCreated:*"]
      }
    ]
  }'
```

### Verifying it works

Upload a file via the app's `POST /project/{id}/documents` endpoint, then
check CloudWatch Logs for the function (`/aws/lambda/project-management-size-limit`)
to confirm it ran and logged the project's running total.
