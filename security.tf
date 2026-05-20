# ---------------------------------------------------------------------------
# Project-Level Security Hardening
# No GCP Organization required — all resources are project-scoped
# ---------------------------------------------------------------------------

# Enable Compute API (required for Cloud Armor)
resource "google_project_service" "compute_api" {
  project            = var.project_id
  service            = "compute.googleapis.com"
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# IAM Audit Logging — records who accessed what on key services
# Visible in Cloud Logging > Audit Logs
# ---------------------------------------------------------------------------
resource "google_project_iam_audit_config" "bigquery_audit" {
  project = var.project_id
  service = "bigquery.googleapis.com"

  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }
  audit_log_config {
    log_type = "ADMIN_READ"
  }
}

resource "google_project_iam_audit_config" "storage_audit" {
  project = var.project_id
  service = "storage.googleapis.com"

  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }
}

# ---------------------------------------------------------------------------
# Cloud Armor WAF — OWASP Top 10 protection
# Attach to any backend service / load balancer via security_policy argument
# ---------------------------------------------------------------------------
resource "google_compute_security_policy" "aviation_waf" {
  project     = var.project_id
  name        = "aviation-waf-policy"
  description = "Cloud Armor WAF policy — OWASP Top 10 protection for aviation lakehouse"

  # Block XSS attacks
  rule {
    action      = "deny(403)"
    priority    = 1000
    description = "Block XSS attacks"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('xss-v33-stable')"
      }
    }
  }

  # Block SQL injection
  rule {
    action      = "deny(403)"
    priority    = 1001
    description = "Block SQL injection attacks"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('sqli-v33-stable')"
      }
    }
  }

  # Block local file inclusion
  rule {
    action      = "deny(403)"
    priority    = 1002
    description = "Block local file inclusion (LFI) attacks"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('lfi-v33-stable')"
      }
    }
  }

  # Block remote file inclusion
  rule {
    action      = "deny(403)"
    priority    = 1003
    description = "Block remote file inclusion (RFI) attacks"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('rfi-v33-stable')"
      }
    }
  }

  # Block remote code execution
  rule {
    action      = "deny(403)"
    priority    = 1004
    description = "Block remote code execution (RCE) attacks"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('rce-v33-stable')"
      }
    }
  }

  # Default allow (required last rule)
  rule {
    action      = "allow"
    priority    = 2147483647
    description = "Default allow — traffic not matching deny rules is permitted"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
  }

  depends_on = [google_project_service.compute_api]
}
