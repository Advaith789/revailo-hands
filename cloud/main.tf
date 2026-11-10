data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  function_name = "${var.name}-worker"
  account_id    = data.aws_caller_identity.current.account_id
}

# --------------------------------------------------------------------------- results table
#
# One item per (job_id, page_no). The key itself is the idempotency guarantee:
# a replayed page can only ever address the item it already wrote.

resource "aws_dynamodb_table" "results" {
  name         = "${var.name}-results"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"
  range_key    = "page_no"

  attribute {
    name = "job_id"
    type = "S"
  }

  attribute {
    name = "page_no"
    type = "N"
  }
}

# --------------------------------------------------------------------------- worker Lambda

data "archive_file" "worker" {
  type        = "zip"
  source_file = "${path.module}/lambda/worker.py"
  output_path = "${path.module}/build/worker.zip"
}

# Created before the function so Lambda never auto-creates an unmanaged one.
resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "worker" {
  name               = "${var.name}-worker"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "worker" {
  statement {
    sid       = "WriteResultsOnly"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.results.arn]
  }

  statement {
    sid       = "OwnLogGroupOnly"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.worker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "worker" {
  name   = "${var.name}-worker"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}

resource "aws_lambda_function" "worker" {
  function_name    = local.function_name
  role             = aws_iam_role.worker.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "worker.handler"
  filename         = data.archive_file.worker.output_path
  source_code_hash = data.archive_file.worker.output_base64sha256
  memory_size      = 128
  timeout          = 10

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.results.name
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.worker.name
  }

  depends_on = [aws_iam_role_policy.worker, aws_cloudwatch_log_group.worker]
}

# --------------------------------------------------------------------------- state machine

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${var.name}-sfn"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

data "aws_iam_policy_document" "sfn" {
  statement {
    sid     = "InvokeWorkerOnly"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.worker.arn,
      "${aws_lambda_function.worker.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "sfn" {
  name   = "${var.name}-sfn"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}

# IAM is eventually consistent. The first apply ran an execution ~2 s after
# the roles' policies were created and got AccessDenied on
# lambda:InvokeFunction even though the policy allows exactly that ARN
# (cloud/proof/run-20261110T180407Z.log). Wait for propagation before
# creating the state machine, the first thing to use them, rather than retrying on
# AccessDenied, which would also hide genuine permission mistakes.
resource "time_sleep" "iam_propagation" {
  create_duration = "15s"

  triggers = {
    worker_policy = aws_iam_role_policy.worker.policy
    sfn_policy    = aws_iam_role_policy.sfn.policy
  }
}

resource "aws_sfn_state_machine" "pages" {
  name     = "${var.name}-pages"
  type     = "STANDARD"
  role_arn = aws_iam_role.sfn.arn

  definition = jsonencode({
    Comment = "Fan out one worker invocation per page; each writes one result per (job_id, page_no)."
    StartAt = "MeasurePages"
    States = {
      MeasurePages = {
        Type           = "Map"
        ItemsPath      = "$.pages"
        MaxConcurrency = var.map_max_concurrency
        ItemSelector = {
          "job_id.$"    = "$.job_id"
          "page_no.$"   = "$$.Map.Item.Value"
          "execution.$" = "$$.Execution.Name"
        }
        ItemProcessor = {
          ProcessorConfig = { Mode = "INLINE" }
          StartAt         = "MeasurePage"
          States = {
            MeasurePage = {
              Type     = "Task"
              Resource = "arn:${data.aws_partition.current.partition}:states:::lambda:invoke"
              Parameters = {
                FunctionName = aws_lambda_function.worker.arn
                "Payload.$"  = "$"
              }
              OutputPath = "$.Payload"
              # Transient Lambda-service errors only. A bad input (ValueError)
              # is not retried; it fails the execution.
              Retry = [{
                ErrorEquals = [
                  "Lambda.ServiceException",
                  "Lambda.AWSLambdaException",
                  "Lambda.SdkClientException",
                  "Lambda.TooManyRequestsException",
                ]
                IntervalSeconds = 1
                MaxAttempts     = 3
                BackoffRate     = 2
                JitterStrategy  = "FULL"
              }]
              End = true
            }
          }
        }
        ResultPath = "$.results"
        End        = true
      }
    }
  })

  depends_on = [time_sleep.iam_propagation]
}
