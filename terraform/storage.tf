resource "google_storage_bucket" "bronze" {
  name     = "openalex-pipeline-bronze"
  location = "EU"

  # Enforce IAM-only access; disable per-object ACLs.
  uniform_bucket_level_access = true

  # Hard guard against accidental public exposure.
  public_access_prevention = "enforced"

  # Prevent Terraform from destroying this bucket.
  lifecycle {
    prevent_destroy = true
  }
}
