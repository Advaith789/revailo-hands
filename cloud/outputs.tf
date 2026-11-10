output "state_machine_arn" {
  description = "ARN of the Standard state machine."
  value       = aws_sfn_state_machine.pages.arn
}

output "table_name" {
  description = "DynamoDB results table (PK job_id, SK page_no)."
  value       = aws_dynamodb_table.results.name
}

output "region" {
  value = var.region
}
