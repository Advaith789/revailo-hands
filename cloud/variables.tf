variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-2"
}

variable "name" {
  description = "Prefix for every resource name. Also used by verify_destroyed.sh."
  type        = string
  default     = "revailo-takeoff-demo"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,40}$", var.name))
    error_message = "name must be 3-40 characters of a-z, 0-9 and '-'."
  }
}

variable "map_max_concurrency" {
  description = "Map state MaxConcurrency. Bounds this execution only; it is NOT the account-wide vision limit (see takeoff-pipeline/REPORT.md)."
  type        = number
  default     = 3
}

variable "log_retention_days" {
  description = "Retention for the worker's log group."
  type        = number
  default     = 1
}
