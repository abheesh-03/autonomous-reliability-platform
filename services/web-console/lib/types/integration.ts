// Mirrors control-plane's real contract exactly
// (services/control-plane/src/control_plane/domain/integration_credential.py).
// `bearer_token` only ever appears on the CREATE response, exactly
// once -- every other shape here is the secret-free, display-safe
// view.

export type ConnectionType = "opentelemetry";
export type CredentialStatus = "active" | "revoked";

export interface IntegrationCredential {
  id: string;
  organization_id: string;
  service_id: string;
  connection_type: ConnectionType;
  credential_id: string;
  status: CredentialStatus;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
  revoked_at: string | null;
  last_verified_telemetry_at: string | null;
}

export interface IntegrationCredentialListResponse {
  items: IntegrationCredential[];
}

export interface IntegrationCredentialCreated {
  credential: IntegrationCredential;
  bearer_token: string;
}
